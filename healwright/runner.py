"""Runs a TestSpec in a real browser, healing broken selectors on the way."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, expect, sync_playwright

from . import dom
from .healer import HeuristicHealer, LLMHealer
from .llm import LLMProvider
from .spec import ELEMENT_ACTIONS, Step, TestSpec


@dataclass
class StepResult:
    index: int
    action: str
    intent: str
    status: str  # "ok" | "resolved" | "healed" | "failed"
    selector: str | None = None
    old_selector: str | None = None
    method: str | None = None
    confidence: float | None = None
    reason: str | None = None
    error: str | None = None
    screenshot: bytes | None = field(default=None, repr=False)  # PNG, only with capture=True


@dataclass
class RunReport:
    test: str
    passed: bool
    duration_s: float
    steps: list[StepResult] = field(default_factory=list)
    base_url: str = ""
    llm: str | None = None          # e.g. "gemini (gemini-3.5-flash-lite)", None = heuristic only
    started_at: str = ""            # local time, for the HTML report

    @property
    def healed(self) -> list[StepResult]:
        return [s for s in self.steps if s.status in ("healed", "resolved")]

    def to_json(self) -> str:
        data = asdict(self)
        for st in data["steps"]:
            st.pop("screenshot", None)  # images go in the HTML report, not the JSON
        return json.dumps(data, indent=2)


class StepFailed(Exception):
    pass


class Runner:
    def __init__(self, provider: LLMProvider | None = None, timeout_ms: int = 3000,
                 probe_ms: int = 1500, headed: bool = False, capture: bool = False):
        self.healers = [HeuristicHealer()] + ([LLMHealer(provider)] if provider else [])
        self.provider = provider
        self.capture = capture  # take screenshots for the HTML report (D-020)
        self.timeout_ms = timeout_ms  # how long actions/assertions may wait
        self.probe_ms = probe_ms      # how long a saved selector gets before we heal (D-009)
        self.headed = headed

    # ---- public -------------------------------------------------------
    def run(self, spec: TestSpec, base_url: str | None = None) -> RunReport:
        base = base_url or spec.base_url or ""
        llm = f"{self.provider.name} ({getattr(self.provider, 'model', '?')})" if self.provider else None
        report = RunReport(test=spec.name, passed=True, duration_s=0, base_url=base, llm=llm,
                           started_at=time.strftime("%Y-%m-%d %H:%M"))
        t0 = time.time()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not self.headed)
            page = browser.new_page()
            for i, step in enumerate(spec.steps):
                res = self._run_step(page, i, step, base)
                report.steps.append(res)
                if res.status == "failed":
                    report.passed = False
                    break
            browser.close()
        report.duration_s = round(time.time() - t0, 2)
        return report

    # ---- internals ----------------------------------------------------
    def _run_step(self, page: Page, i: int, step: Step, base: str) -> StepResult:
        res = StepResult(i, step.action, step.intent, "ok")
        try:
            if step.action == "goto":
                page.goto(urljoin(base, step.value or ""))
                return res
            assert step.action in ELEMENT_ACTIONS

            sel = step.selector
            if sel and self._usable(page, sel):
                res.selector = sel
            else:
                # Selector missing (first run) or broken (page changed) -> heal.
                heal = self._heal(page, step)
                if heal is None:
                    llm_errors = [h.last_error for h in self.healers if getattr(h, "last_error", None)]
                    raise StepFailed(
                        f"Could not find element for: {step.intent!r}"
                        + (f" (old selector {sel!r} no longer matches)" if sel else "")
                        + (f" [{llm_errors[0]}]" if llm_errors else "")
                    )
                new_sel = dom.best_selector(page, heal.candidate, step.action)
                res.status = "healed" if sel else "resolved"
                res.old_selector, res.selector = sel, new_sel
                res.method, res.confidence, res.reason = heal.method, heal.confidence, heal.reason
                if self.capture:
                    res.screenshot = self._snap_element(page, new_sel)

            self._act(page, step, res.selector)
            # Remember what the element looks like now, for future heals.
            fp = dom.fingerprint(page, res.selector)
            step.fingerprint = {k: v for k, v in fp.items() if v}  # keep the YAML readable
            step.selector = res.selector
        except Exception as e:  # noqa: BLE001 - every failure becomes a report line
            res.status = "failed"
            res.error = str(e).splitlines()[0][:300]
            if self.capture:
                try:
                    res.screenshot = self._snap_page(page)
                except Exception:
                    pass
        return res

    def _snap_page(self, page: Page) -> bytes:
        """The visible page, cropped below the last content so there's no empty space."""
        vw, vh = page.viewport_size["width"], page.viewport_size["height"]
        bottom = page.evaluate("""() => {
            let b = 0;
            for (const el of document.body.querySelectorAll('*')) {
                const r = el.getBoundingClientRect();
                if (r.width && r.height) b = Math.max(b, r.bottom);
            }
            return b; }""")
        h = min(max(bottom + 30, 200), vh)
        return page.screenshot(clip={"x": 0, "y": 0, "width": vw, "height": h})

    def _snap_element(self, page: Page, sel: str) -> bytes | None:
        """Picture of the element and its surroundings, outlined, for the HTML report."""
        try:
            loc = page.locator(sel)
            loc.scroll_into_view_if_needed(timeout=self.timeout_ms)
            box = loc.bounding_box()
            if not box:
                return None
            prev = loc.evaluate("el => [el.style.outline, el.style.outlineOffset]")
            loc.evaluate("el => { el.style.outline = '3px solid #e8590c'; el.style.outlineOffset = '3px'; }")
            vw, vh = page.viewport_size["width"], page.viewport_size["height"]
            # A readable cutout centred on the element: at least 360x180, at most 600 wide,
            # so very wide elements (banners) don't become a thin unreadable strip.
            pad = 70
            w = min(max(box["width"] + 2 * pad, 360), 600, vw)
            h = min(max(box["height"] + 2 * pad, 180), vh)
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            x = min(max(cx - w / 2, 0), vw - w)
            if box["width"] + 2 * pad > w:  # wide element: show its left part, where text starts
                x = min(max(box["x"] - 20, 0), vw - w)
            y = min(max(cy - h / 2, 0), vh - h)
            png = page.screenshot(clip={"x": x, "y": y, "width": w, "height": h})
            loc.evaluate("(el, p) => { el.style.outline = p[0]; el.style.outlineOffset = p[1]; }", prev)
            return png
        except Exception:
            return None  # a missing picture must never fail the test

    def _usable(self, page: Page, sel: str) -> bool:
        try:
            page.wait_for_load_state("load", timeout=self.timeout_ms)
            page.locator(sel).wait_for(state="visible", timeout=self.probe_ms)
            return True
        except Exception:
            return False

    def _heal(self, page: Page, step: Step):
        must = step.value if step.action == "expect_text" else None
        if must:  # give late-appearing text a chance before we look
            try:
                page.get_by_text(must).first.wait_for(timeout=self.timeout_ms)
            except Exception:
                pass
        cands = dom.candidates(page, step.action, must_contain=must)
        for healer in self.healers:
            result = healer.heal(step, cands)
            if result:
                return result
        return None

    def _act(self, page: Page, step: Step, sel: str) -> None:
        loc = page.locator(sel)
        if step.action == "click":
            loc.click(timeout=self.timeout_ms)
        elif step.action == "fill":
            loc.fill(step.value or "", timeout=self.timeout_ms)
        elif step.action == "expect_text":
            expect(loc).to_contain_text(step.value or "", timeout=self.timeout_ms)
        elif step.action == "expect_visible":
            expect(loc).to_be_visible(timeout=self.timeout_ms)


def run_file(path: str | Path, base_url: str | None = None, update: bool = False,
             provider: LLMProvider | None = None, headed: bool = False,
             capture: bool = False) -> RunReport:
    spec = TestSpec.load(path)
    report = Runner(provider=provider, headed=headed, capture=capture).run(spec, base_url=base_url)
    if update and report.passed:
        spec.save(path)  # only a fully passing run may rewrite the test (DECISIONS D-007)
    return report
