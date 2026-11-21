"""Finding the right element when a selector is missing or broken.

Order (DECISIONS D-004):
  1. HeuristicHealer - free, fast, offline. Scores every candidate against the
     saved fingerprint and the step's intent. Accepts only a confident, clear winner.
  2. LLMHealer - asked only if the heuristic is not confident. Picks a candidate
     by index; it never invents selectors, so it cannot hallucinate one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .llm import LLMProvider, extract_json
from .spec import Step

STOPWORDS = {
    "the", "a", "an", "on", "in", "into", "to", "of", "and", "or", "with", "for", "at",
    "click", "press", "tap", "enter", "type", "fill", "check", "that", "see", "shows",
    "should", "is", "be", "visible", "page", "field", "box", "input", "button", "link", "it",
}

# Confidence rules for the heuristic (tuned on the demo + tests; see BUILD_LOG).
MIN_CONFIDENCE = 0.35          # with a saved fingerprint (healing)
MIN_CONFIDENCE_NO_FP = 0.67    # first run, intent words only: be strict (D-008)
MIN_MARGIN = 0.15


@dataclass
class HealResult:
    candidate: dict
    confidence: float
    method: str  # "heuristic" or "llm"
    reason: str


def _sim(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _words(s: str) -> set[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s or "")  # camelCase -> camel Case
    return {w for w in re.split(r"[^a-z0-9]+", s.lower()) if w and w not in STOPWORDS}


def _compatible(action: str, c: dict) -> bool:
    if action == "fill":
        return c["tag"] in ("input", "textarea") or c.get("role") == "textbox" or c["tag"] not in ("button", "a")
    if action == "click":
        return not (c["tag"] == "input" and c.get("type") in ("", "text", "email", "password", "search", "tel", "url", "number"))
    return True


def score(c: dict, step: Step) -> tuple[float, float]:
    """Return (score, max_possible) for candidate ``c`` against ``step``."""
    fp = step.fingerprint or {}
    s = 0.0
    top = 0.0

    if fp:
        top += 1
        s += 1 if fp.get("tag") == c["tag"] else 0
        for key, w in (("testid", 4), ("id", 3), ("name", 2), ("href", 2)):
            if fp.get(key):
                top += w
                s += w if fp[key] == c.get(key) else w * 0.5 * _sim(fp[key], c.get(key, ""))
        for key, w in (("text", 3), ("aria_label", 2), ("placeholder", 2), ("label", 2)):
            if fp.get(key):
                top += w
                s += w * _sim(fp[key], c.get(key, ""))
        if fp.get("type"):
            top += 1.5
            s += 1.5 if fp["type"] == c.get("type") else 0
        if fp.get("classes"):
            top += 1
            a, b = set(fp["classes"].split()), set(c.get("classes", "").split())
            s += len(a & b) / len(a | b) if (a | b) else 0

    # Intent words ("the login button") vs what the candidate says about itself.
    intent = _words(step.intent)
    if intent:
        top += 3
        cand_words = set()
        for key in ("text", "aria_label", "placeholder", "label", "name", "id", "testid", "type"):
            cand_words |= _words(c.get(key, ""))
        s += 3 * len(intent & cand_words) / len(intent)

    if step.action == "expect_text" and step.value:
        top += 3
        s += 3 if step.value.lower() in c.get("text", "").lower() else 0

    return s, max(top, 1.0)


class HeuristicHealer:
    method = "heuristic"

    def heal(self, step: Step, cands: list[dict]) -> HealResult | None:
        ranked = []
        for c in cands:
            if not _compatible(step.action, c):
                continue
            s, top = score(c, step)
            ranked.append((s / top, c))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0], reverse=True)
        best_conf, best = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_conf - runner_up
        threshold = MIN_CONFIDENCE if step.fingerprint else MIN_CONFIDENCE_NO_FP
        if best_conf >= threshold and margin >= MIN_MARGIN:
            return HealResult(best, round(best_conf, 2), self.method,
                              f"best match {best_conf:.2f}, next {runner_up:.2f}")
        return None


LLM_SYSTEM = (
    "You help a UI test runner find the element a test step refers to after the page changed. "
    "You will get the step, what the element looked like before (may be empty), and a numbered list "
    "of candidate elements currently on the page. Choose the candidate the step means. "
    'Reply with JSON only: {"index": <number or null>, "confidence": <0..1>, "reason": "<short>"}. '
    "Use null if none of them fits."
)


class LLMHealer:
    method = "llm"
    MAX_IN_PROMPT = 120

    def __init__(self, provider: LLMProvider, min_confidence: float = 0.6):
        self.provider = provider
        self.min_confidence = min_confidence
        self.last_error: str | None = None  # shown in the report if healing fails

    def heal(self, step: Step, cands: list[dict]) -> HealResult | None:
        cands = [c for c in cands if _compatible(step.action, c)][: self.MAX_IN_PROMPT]
        if not cands:
            return None
        listing = "\n".join(
            f"{i}: " + json.dumps({k: v for k, v in c.items() if v and k != "path"})
            for i, c in enumerate(cands)
        )
        user = (
            f"Step action: {step.action}\nStep intent: {step.intent}\n"
            f"Step value: {step.value or ''}\nOld selector: {step.selector or '(none)'}\n"
            f"Element before: {json.dumps(step.fingerprint or {})}\n\nCandidates:\n{listing}"
        )
        self.last_error = None
        try:
            data = extract_json(self.provider.complete(LLM_SYSTEM, user))
            idx = data.get("index")
            conf = float(data.get("confidence", 0))
        except Exception as e:  # network, rate limit, bad JSON: heal fails, run continues
            self.last_error = f"LLM error: {e}"
            return None
        if idx is None or not (0 <= int(idx) < len(cands)) or conf < self.min_confidence:
            return None
        return HealResult(cands[int(idx)], round(conf, 2), self.method, str(data.get("reason", "")))
