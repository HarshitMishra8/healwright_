"""HTML report (D-020): content, screenshots, safety, and the CLI flag."""

import json

from click.testing import CliRunner

from healwright.cli import main
from healwright.report import render_html
from healwright.runner import RunReport, StepResult, run_file


def test_healed_run_report_has_summary_selectors_and_pictures(login_spec, v1_url, v2_url):
    run_file(login_spec, base_url=v1_url, update=True)
    report = run_file(login_spec, base_url=v2_url, capture=True)
    html = render_html(report)
    assert "PASSED" in html and "Healed" in html
    assert 'input[id=&quot;username&quot;]' in html          # old selector (escaped)
    assert 'input[id=&quot;user-field&quot;]' in html        # new selector
    assert html.count("data:image/png;base64,") >= 8         # 4 healed steps, link + img each
    assert all(s.screenshot for s in report.steps[1:])


def test_failed_run_report_shows_error_and_page_picture(tmp_path, v1_url):
    spec = tmp_path / "t.yaml"
    spec.write_text("name: fail\nsteps:\n"
                    "- {action: goto, intent: open, value: login.html}\n"
                    "- {action: click, intent: the Delete account button}\n")
    report = run_file(spec, base_url=v1_url, capture=True)
    html = render_html(report)
    assert "FAILED" in html and "Could not find element" in html
    assert report.steps[-1].screenshot                          # whole-page picture of the failure
    assert 'class="shot wide"' in html


def test_untrusted_text_is_escaped():
    """Test names, intents, LLM reasons and page text must never run as HTML."""
    evil = '<script>alert("x")</script>'
    r = RunReport(test=evil, passed=False, duration_s=1, steps=[
        StepResult(0, "click", evil, "healed", selector=evil, old_selector="#a",
                   method="llm", confidence=0.9, reason=evil),
        StepResult(1, "click", "x", "failed", error=evil),
    ])
    html = render_html(r)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_no_screenshots_without_capture(login_spec, v1_url):
    report = run_file(login_spec, base_url=v1_url)
    assert not any(s.screenshot for s in report.steps)


def test_json_report_never_contains_images(login_spec, v1_url):
    report = run_file(login_spec, base_url=v1_url, capture=True)
    data = json.loads(report.to_json())
    assert all("screenshot" not in s for s in data["steps"])


def test_cli_html_flag_writes_report(login_spec, v1_url, tmp_path):
    out = tmp_path / "report.html"
    res = CliRunner().invoke(main, ["run", str(login_spec), "--base-url", v1_url,
                                    "--no-llm", "--html", str(out)])
    assert res.exit_code == 0, res.output
    assert out.exists() and "Healwright report" in out.read_text()
    assert "HTML report:" in res.output
