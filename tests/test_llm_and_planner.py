"""LLM features, tested offline with FakeProvider (no API key, no network)."""

import json
import re

from healwright.llm import FakeProvider, extract_json
from healwright.planner import export_pytest, plan
from healwright.runner import run_file
from healwright.spec import TestSpec


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('Sure!\n```json\n{"index": 2}\n```') == {"index": 2}
    assert extract_json('Here: [1, 2] done') == [1, 2]


def test_llm_healer_used_when_heuristic_is_unsure(tmp_path, v2_url):
    # "the primary action" shares no words with any element, so the heuristic gives up.
    spec = tmp_path / "t.yaml"
    spec.write_text(
        "name: llm\nsteps:\n"
        "- {action: goto, intent: open, value: login.html}\n"
        "- {action: click, intent: the primary action}\n"
    )

    def responder(system, user):
        idx = next(int(m.group(1)) for m in re.finditer(r"^(\d+): (.*)$", user, re.M)
                   if "Log in to Acme" in m.group(2))
        return json.dumps({"index": idx, "confidence": 0.9, "reason": "submit button"})

    fake = FakeProvider(responder)
    report = run_file(spec, base_url=v2_url, provider=fake)
    assert report.passed
    assert report.steps[1].method == "llm"
    assert len(fake.calls) == 1


def test_llm_low_confidence_is_rejected(tmp_path, v2_url):
    spec = tmp_path / "t.yaml"
    spec.write_text(
        "name: llm\nsteps:\n"
        "- {action: goto, intent: open, value: login.html}\n"
        "- {action: click, intent: the primary action}\n"
    )
    fake = FakeProvider(lambda s, u: '{"index": 0, "confidence": 0.3, "reason": "guess"}')
    assert not run_file(spec, base_url=v2_url, provider=fake).passed


def test_plan_from_plain_english():
    reply = json.dumps({"name": "login works", "steps": [
        {"action": "fill", "intent": "the username field", "value": "asha"},
        {"action": "click", "intent": "the Log in button", "selector": "#ignored"},
    ]})
    spec = plan("Log in as asha", FakeProvider(lambda s, u: reply), start_url="login.html")
    assert spec.steps[0].action == "goto"          # start URL inserted
    assert spec.steps[2].selector is None          # LLM-written selectors are dropped (D-003)


def test_export_generates_valid_python(login_spec, v1_url):
    run_file(login_spec, base_url=v1_url, update=True)
    code = export_pytest(TestSpec.load(login_spec), base_url=v1_url)
    compile(code, "generated.py", "exec")
    assert 'page.locator(\'input[id="username"]\').fill(\'asha\')' in code
