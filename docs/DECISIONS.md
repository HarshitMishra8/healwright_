# Decision Log

Every meaningful choice in this project, why we made it, and what we gave up.
**Rule:** never delete an entry. If a decision changes, add a new one and mark the
old one `Superseded by D-0xx`.

Template for new entries:

```
## D-0xx: <title>
- Date: YYYY-MM-DD | Status: Accepted / Superseded by D-0yy / Revisit
- Context: what problem forced a choice
- Decision: what we chose
- Alternatives: what else we considered and why not
- Consequences: what this makes easy, hard, or risky
```

---

## D-001: Build in Python
- Date: 2026-11-19 | Status: Accepted (chosen by project owner)
- Context: Playwright supports Python, TypeScript, Java and .NET. We need one.
- Decision: Python 3.10+.
- Alternatives: TypeScript is Playwright's "home" language and what many companies
  write their tests in, but it has a steeper learning curve for the owner.
- Consequences: Easy to read and learn from, and good AI and testing libraries.
  Later we may want a TypeScript *export* so teams on TS can use our output (see roadmap).

## D-002: Working name "Healwright"
- Date: 2026-11-19 | Status: Accepted, Revisit before first public release
- Context: The package, CLI command and repo need a name.
- Decision: `healwright` ("heal" + Playwright).
- Alternatives: none seriously considered yet.
- Consequences: We have NOT checked PyPI or GitHub availability or trademarks yet,
  because there was no network in the build session. Check this before publishing.

## D-003: Tests are plain-English intents; selectors are only a cache
- Date: 2026-11-19 | Status: Accepted
- Context: Normal Playwright tests hard-code selectors like `#login-btn`, which break
  whenever the front end changes. That breakage is the problem we solve.
- Decision: Each step in the YAML spec is `action` + `intent` (e.g. "the Log in
  button") + optional `value`. `selector` and `fingerprint` are filled in and
  maintained by the tool. The intent is the source of truth.
  The LLM planner writes intents only; any selector it returns is thrown away.
- Alternatives: (a) Let the LLM write selectors directly. Rejected because LLMs guess
  selectors that don't exist. (b) Pure natural-language execution with an LLM on
  every step. Rejected as slow, costly and non-deterministic.
- Consequences: Tests read like documentation and survive redesigns. Normal runs
  use cached selectors, so they're as fast as plain Playwright.

## D-004: Heal with heuristics first, LLM only as a fallback
- Date: 2026-11-19 | Status: Accepted
- Context: Healing needs to be cheap, fast, and safe.
- Decision: `HeuristicHealer` scores every candidate element against the saved
  fingerprint and the intent words. If it is not confident, `LLMHealer` is asked to
  pick a candidate **by index** from the list. It can never invent a selector.
- Alternatives: LLM-only healing. Rejected because it costs money on every heal and
  can't run offline or in tests.
- Consequences: Most heals are free and deterministic. The LLM is optional, and the
  tool works with no API key.

## D-005: Selector preference order
- Date: 2026-11-19 | Status: Accepted
- Context: After healing we must write a new selector. Some selectors are much more
  stable than others.
- Decision: The first one that matches exactly one element wins, in this order:
  `data-testid` > `id` (skipped if it looks auto-generated) > `name` > `aria-label` >
  `placeholder` > `role` > visible text > full CSS path. For `expect_text` steps we
  never select by text, because the text is the thing being checked.
- Consequences: Healed selectors are as stable as the page allows. The last option,
  a CSS path, is fragile but always works.

## D-006: Pluggable LLM provider, Anthropic via standard library
- Date: 2026-11-19 | Status: Accepted
- Context: We want LLM features, testable offline, with few dependencies.
- Decision: An `LLMProvider` protocol with one method, `complete(system, user)`.
  `AnthropicProvider` calls the Messages API using only `urllib` (no SDK).
  `FakeProvider` is used in tests. The model can be set with `HEALWRIGHT_MODEL`
  (default `claude-sonnet-5-5`).
- Alternatives: The official SDK. Not installable in the build session, and it adds a
  dependency for one HTTP call.
- Consequences: Adding OpenAI, Gemini or a local model means one small class.
  NOTE: the real API call has not yet been tested live. See BUILD_LOG next steps.

## D-007: Only a passing run may rewrite the test file
- Date: 2026-11-19 | Status: Accepted
- Context: Auto-saving healed selectors is convenient, but a wrong heal saved to disk
  silently corrupts the test.
- Decision: The spec is rewritten only with `--update`, and only if every step passed.
  Without `--update` we report heals and suggest re-running with `--update`.
- Consequences: Users stay in control. In CI you would run without `--update` and
  review heals in the report.

## D-008: Stricter confidence when there is no fingerprint
- Date: 2026-11-19 | Status: Accepted
- Context: Bug found in session 1: on a first run (intent only, no fingerprint),
  "the Delete account button" was matched to "Create account" at 0.5 confidence, so
  a test that should fail passed. That is the worst failure mode for a test tool.
- Decision: Intent-only matches need confidence >= 0.67. Fingerprint-based heals need
  >= 0.35. Both also need a 0.15 lead over the second-best candidate.
- Alternatives: One global threshold. It was either too strict for heals or too loose
  for first runs.
- Consequences: A regression test locks this in (`test_intent_only_refuses_partial_match`).
  Some valid first-run matches may now go to the LLM or fail. That is acceptable.

## D-009: 1.5s probe before healing
- Date: 2026-11-19 | Status: Accepted, Revisit with real-world sites
- Context: A broken selector originally waited the full 3s action timeout before
  healing. The v2 demo took 12.5s.
- Decision: Wait for the page `load` event, then give the saved selector 1.5s
  (`probe_ms`) to appear before healing. Actions still get 3s.
- Consequences: The v2 demo dropped to about 6.6s. Risk: on slow apps, an element that
  takes over 1.5s to appear may trigger an unneeded heal. Make `probe_ms` a CLI flag if
  this shows up.

## D-010: Ship a "before/after" demo site as the built-in proof
- Date: 2026-11-19 | Status: Accepted
- Context: Recruiters and buyers need to *see* healing work in under a minute.
- Decision: `examples/demo_site/v1` and `v2`. v2 is a "redesign" that changes every
  id, name, class and label, and the wording of the button. The test suite runs
  v1 -> v2 on every change.
- Consequences: It doubles as a regression benchmark. Later: add harder pages.

## D-011: Open source under MIT
- Date: 2026-11-19 | Status: Superseded by D-018
- Context: The strategy is open-source core for resume visibility, then a paid hosted
  version later.
- Decision: MIT license.
- Alternatives: AGPL, which protects against others hosting it commercially but scares
  off company users.
- Consequences: Anyone can use it, including commercially. Paid value has to come from
  hosting, dashboards and team features, not the core.

## D-012: v0.1 scope
- Date: 2026-11-19 | Status: Accepted
- Decision: Five actions: `goto`, `click`, `fill`, `expect_text`, `expect_visible`.
  Chromium only. CLI only.
- Out of scope for now: dropdowns (`select`), hover, file upload, iframes, shadow DOM,
  multiple tabs, secrets handling, HTML report, CI integration.
- Consequences: Small enough to finish and demo. The roadmap in the README orders what
  comes next.

## D-013: GitHub Actions CI on the oldest and newest supported Python
- Date: 2026-11-19 | Status: Accepted
- Context: A green "tests passing" badge is the first thing a recruiter sees on a repo,
  and CI stops us from breaking healing without noticing.
- Decision: `.github/workflows/tests.yml` runs `pytest` (including the real-browser
  tests) on every push to `main` and every pull request, on Python 3.10 and 3.13.
- Alternatives: Test every version from 3.10 to 3.13. That's twice the CI minutes for
  little gain, because the oldest and newest catch almost all version problems.
- Consequences: Each run installs Chromium (about 1 to 2 min). Free for public repos.

## D-014: Git conventions
- Date: 2026-11-19 | Status: Accepted
- Decision: Default branch `main`. Small commits, each with a short imperative summary
  ("Add select action"). Every work session ends with a BUILD_LOG entry in the same
  commit as the work it describes.
- Consequences: `git log` plus BUILD_LOG together give the full history of what and why.

## D-015: Support free LLMs via one OpenAI-compatible provider
- Date: 2026-11-19 | Status: Accepted (extends D-006)
- Context: Anthropic API credits start at $5 (about ₹530 with GST). That's too much for a
  student to pay just to test, and users of the tool will feel the same.
- Decision: Add `OpenAICompatibleProvider`, one class that speaks the common
  `/chat/completions` format, with presets for **Gemini** (free tier, default model
  `gemini-3.8-flash`) and **Ollama** (free, local, default `llama3.2`), plus a generic
  mode for any other compatible API. Choose with `HEALWRIGHT_PROVIDER`, or auto-detect
  from `ANTHROPIC_API_KEY` then `GEMINI_API_KEY`.
- Alternatives: A separate class per vendor. More code and more to maintain. Native Gemini
  API: richer features, but a different format we'd need a second client for.
- Consequences: The tool can be used and tested for ₹0. "Works with local models" is also a
  selling point for companies that can't send their pages to a cloud AI. Risk: free-tier
  limits and model names change often. Google cut Gemini's free quotas in Dec 2025 and
  Apr 2026, so the default model may need updating. `HEALWRIGHT_MODEL` overrides it without
  a code change.

## D-016: Harshit Mishra is the only author and contributor
- Date: 2026-11-21 | Status: Accepted (chosen by project owner; amends D-014)
- Context: Early commits were made with the AI assistant's git identity and had
  "Co-Authored-By: Claude" lines, so GitHub listed Claude as a contributor.
- Decision: Every commit is authored by Harshit Mishra, with no AI co-author or session
  lines. History was rewritten once (`git filter-branch`) and force-pushed to fix the
  existing commits.
- Consequences: Commit hashes changed once. Any other clone has to be re-cloned.
  Patches from AI sessions must use Harshit's identity and no trailers. If they don't,
  re-run the fix before pushing.

## D-017: Retry busy LLM servers, and explain failures in plain words
- Date: 2026-11-21 | Status: Accepted
- Context: The first live Gemini call returned **HTTP 503 (server busy)**, and the tool
  crashed with a 40-line traceback. Free tiers often return 503 and 429 (rate limit).
- Decision: All LLM HTTP calls go through `post_json()`. It retries 429/500/502/503/504
  up to 3 times (waits 2s, 5s, 10s, or the server's `Retry-After`). Other errors (401 bad
  key, 404 bad model ...) fail at once with a one-line hint. During `run`, an LLM failure
  doesn't crash the run: the step fails and its error says why (`LLM error: HTTP 503 ...`).
- Alternatives: Retry forever. Rejected because it could hang CI. No retries. Rejected
  because free tiers would fail too often.
- Consequences: A busy server costs up to about 17s before giving up. 5 new tests use a
  local "flaky" server to check retry, give-up, no-retry-on-bad-key and unreachable cases.

## D-018: No open-source license (all rights reserved)
- Date: 2026-11-21 | Status: Accepted (chosen by project owner; supersedes D-011)
- Context: The owner doesn't want to grant others the right to reuse the code, and may sell
  the tool later.
- Decision: Remove `LICENSE` and the MIT line from `pyproject.toml`. The README states
  "© 2026 Harshit Mishra. All rights reserved."
- Alternatives: MIT (anyone may use or sell it). A "source-available" license that allows
  viewing but not commercial use. Can be added later if needed.
- Consequences: The repo stays public, so recruiters can read it, but nobody may legally copy
  or reuse the code without permission. Companies won't adopt it as open source. That's fine
  for a portfolio and keeps selling options open. A license can be added any time later;
  taking one back is much harder, so starting without one is the safer default.
