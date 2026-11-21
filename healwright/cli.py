"""Command line: healwright run | plan | export."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .llm import LLMError, default_provider
from .planner import export_pytest, plan
from .runner import run_file
from .spec import TestSpec

ICONS = {"ok": "PASS ", "resolved": "FOUND", "healed": "HEAL ", "failed": "FAIL "}


def _provider():
    try:
        return default_provider()
    except RuntimeError as e:  # misconfigured env vars -> clean message, no traceback
        raise click.ClickException(str(e)) from e


@click.group()
def main() -> None:
    """Healwright: self-healing Playwright tests written in plain English."""


@main.command()
@click.argument("spec_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--base-url", help="Prefix for relative goto URLs (overrides the spec).")
@click.option("--update", is_flag=True, help="Save found/healed selectors back into the spec (only if the run passes).")
@click.option("--no-llm", is_flag=True, help="Heuristic healing only, even if ANTHROPIC_API_KEY is set.")
@click.option("--headed", is_flag=True, help="Show the browser window.")
@click.option("--report", "report_path", type=click.Path(dir_okay=False), help="Write a JSON report here.")
def run(spec_path, base_url, update, no_llm, headed, report_path) -> None:
    """Run a test spec, healing broken selectors."""
    provider = None if no_llm else _provider()
    click.echo(f"LLM healing: {f'on ({provider.name}, {provider.model})' if provider else 'off'}")
    report = run_file(spec_path, base_url=base_url, update=update, provider=provider, headed=headed)

    for s in report.steps:
        line = f"[{ICONS[s.status]}] {s.index + 1}. {s.action:<14} {s.intent}"
        if s.status in ("healed", "resolved"):
            line += f"\n           -> {s.selector}  ({s.method}, confidence {s.confidence})"
            if s.old_selector:
                line += f"\n           was {s.old_selector}"
        if s.error:
            line += f"\n           {s.error}"
        click.echo(line)

    click.echo(f"\n{'PASSED' if report.passed else 'FAILED'} in {report.duration_s}s, "
               f"{len(report.healed)} step(s) found/healed")
    if report.healed and not update:
        click.echo("Tip: re-run with --update to save the new selectors into the spec.")
    if report_path:
        Path(report_path).write_text(report.to_json(), encoding="utf-8")
    sys.exit(0 if report.passed else 1)


@main.command("plan")
@click.argument("description")
@click.option("--url", help="Start URL to open first.")
@click.option("-o", "--out", required=True, type=click.Path(dir_okay=False), help="Spec file to write.")
def plan_cmd(description, url, out) -> None:
    """Turn a plain-English DESCRIPTION into a test spec (needs an LLM; see README)."""
    provider = _provider()
    if not provider:
        raise click.ClickException(
            "No LLM configured. Free option: set GEMINI_API_KEY, or HEALWRIGHT_PROVIDER=ollama. See README.")
    click.echo(f"Using {provider.name} ({provider.model})")
    try:
        spec = plan(description, provider, start_url=url)
    except LLMError as e:
        raise click.ClickException(f"{provider.name} failed: {e}") from e
    except (ValueError, KeyError) as e:  # model replied, but not with usable JSON
        raise click.ClickException(f"{provider.name} gave an answer we couldn't read: {e}") from e
    spec.save(out)
    click.echo(f"Wrote {len(spec.steps)} steps to {out}. Run it with --update to find selectors.")


@main.command()
@click.argument("spec_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--out", required=True, type=click.Path(dir_okay=False))
@click.option("--base-url", default="")
def export(spec_path, out, base_url) -> None:
    """Export a spec (with selectors) to a plain pytest-playwright file."""
    Path(out).write_text(export_pytest(TestSpec.load(spec_path), base_url), encoding="utf-8")
    click.echo(f"Wrote {out}")


if __name__ == "__main__":
    main()
