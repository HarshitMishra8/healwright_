"""Unit tests for the scoring logic: no browser needed."""

from healwright.healer import HeuristicHealer
from healwright.spec import Step


def cand(**kw):
    base = {"tag": "button", "id": "", "name": "", "type": "", "text": "", "aria_label": "",
            "placeholder": "", "role": "", "testid": "", "classes": "", "href": "", "label": "", "path": "x"}
    base.update(kw)
    return base


def test_intent_only_picks_exact_match():
    step = Step(action="click", intent="the Log in button")
    cands = [cand(text="Create account"), cand(text="Log in", type="submit")]
    res = HeuristicHealer().heal(step, cands)
    assert res and res.candidate["text"] == "Log in"


def test_intent_only_refuses_partial_match():
    # "Delete account" must NOT be matched to "Create account" (BUILD_LOG session 1, bug 3).
    step = Step(action="click", intent="the Delete account button")
    cands = [cand(text="Create account"), cand(text="Log in")]
    assert HeuristicHealer().heal(step, cands) is None


def test_fingerprint_heals_renamed_id():
    step = Step(action="fill", intent="the password field",
                fingerprint={"tag": "input", "id": "password", "type": "password", "placeholder": "Password"})
    cands = [cand(tag="input", id="user-field", placeholder="Email or username"),
             cand(tag="input", id="pass-field", type="password", placeholder="Your password")]
    res = HeuristicHealer().heal(step, cands)
    assert res and res.candidate["id"] == "pass-field"


def test_ambiguous_tie_is_refused():
    step = Step(action="click", intent="the Save button")
    cands = [cand(text="Save"), cand(text="Save")]
    assert HeuristicHealer().heal(step, cands) is None


def test_click_never_targets_text_input():
    step = Step(action="click", intent="the search")
    cands = [cand(tag="input", type="text", placeholder="search")]
    assert HeuristicHealer().heal(step, cands) is None
