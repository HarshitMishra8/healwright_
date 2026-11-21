"""End-to-end tests in a real (headless) Chromium against the demo site."""

from healwright.runner import run_file
from healwright.spec import TestSpec


def test_first_run_finds_selectors_and_saves_them(login_spec, v1_url):
    report = run_file(login_spec, base_url=v1_url, update=True)
    assert report.passed
    assert [s.status for s in report.steps[1:]] == ["resolved"] * 4
    saved = TestSpec.load(login_spec)
    assert all(s.selector and s.fingerprint for s in saved.steps[1:])


def test_second_run_needs_no_healing(login_spec, v1_url):
    run_file(login_spec, base_url=v1_url, update=True)
    report = run_file(login_spec, base_url=v1_url)
    assert report.passed and not report.healed


def test_heals_after_redesign(login_spec, v1_url, v2_url):
    run_file(login_spec, base_url=v1_url, update=True)
    report = run_file(login_spec, base_url=v2_url, update=True)
    assert report.passed
    assert [s.status for s in report.steps[1:]] == ["healed"] * 4
    # The assertion step must not be located by the very text it checks.
    assert "Welcome" not in report.steps[-1].selector
    # After --update, v2 runs clean.
    assert not run_file(login_spec, base_url=v2_url).healed


def test_unrelated_page_fails_instead_of_false_heal(login_spec, v1_url, tmp_path):
    run_file(login_spec, base_url=v1_url, update=True)
    other = tmp_path / "site"
    other.mkdir()
    (other / "login.html").write_text(
        "<h1>Reports</h1><input placeholder='Search'><button>Export</button><button>Settings</button>"
    )
    report = run_file(login_spec, base_url=other.as_uri() + "/")
    assert not report.passed
    assert report.steps[-1].status == "failed"


def test_failed_run_does_not_rewrite_spec(login_spec, tmp_path):
    before = login_spec.read_text()
    site = tmp_path / "s"
    site.mkdir()
    (site / "login.html").write_text("<p>nothing here</p>")
    report = run_file(login_spec, base_url=site.as_uri() + "/", update=True)
    assert not report.passed
    assert login_spec.read_text() == before
