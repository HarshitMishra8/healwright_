# Build Log

A diary of every work session: what we did, how, what broke, and what's next.
Newest session at the bottom. Decisions are in [DECISIONS.md](DECISIONS.md) and
are referenced here as D-0xx.

## How to pick this project up again

1. Read the **latest session** below, especially "Next steps".
2. Skim [DECISIONS.md](DECISIONS.md) so you don't re-argue settled choices.
3. Set up and check everything still works:
   ```bash
   cd healwright
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   playwright install chromium
   pytest -q                 # expect: all tests pass
   ```
4. At the end of every session, add a new "Session N" entry using the same headings.

---

## Session 1: 2026-11-19, from idea to working v0.1

**Goal:** Build version 1 of a self-healing Playwright test tool. It writes tests from
plain English and fixes broken selectors. It's meant as a resume project with a path
to selling later.

### What we built
| File | What it does |
|---|---|
| `healwright/spec.py` | The YAML test format: steps with `action`, `intent`, `value`, plus auto-managed `selector` and `fingerprint` (D-003) |
| `healwright/dom.py` | JavaScript run inside the page: takes an element's *fingerprint*, lists candidate elements, and builds the most stable unique selector (D-005) |
| `healwright/healer.py` | `HeuristicHealer` (scoring) and `LLMHealer` (picks a candidate by index) (D-004, D-008) |
| `healwright/llm.py` | `AnthropicProvider` (stdlib HTTP), `FakeProvider` for tests, JSON extraction (D-006) |
| `healwright/runner.py` | Runs a spec in Chromium: tries the saved selector, heals if broken, records results, refreshes fingerprints (D-007, D-009) |
| `healwright/planner.py` | `plan()`: plain English to spec via LLM. `export_pytest()`: spec to plain Playwright code |
| `healwright/cli.py` | `healwright run / plan / export` |
| `examples/demo_site/v1`, `v2` | Login page, and a "redesigned" version that breaks every selector (D-010) |
| `examples/login_test.yaml` | Example test written only as intents |
| `tests/` | 15 tests: scoring units, real-browser end-to-end, LLM features with a fake provider |

### How it works (the core idea)
1. **First run** (`--update`): steps have no selectors, so the healer *resolves* each one
   from the intent words. It saves the selector plus a fingerprint of the element: its tag,
   id, name, text, label, placeholder and classes.
2. **Normal runs:** use the saved selector, which is as fast as plain Playwright.
3. **After a UI change:** the saved selector fails, so we list every visible candidate,
   score each against the old fingerprint and the intent, and accept only a confident,
   clear winner. If the heuristic is unsure, an LLM picks from the list. The new selector
   is reported and saved only with `--update` on a passing run.

### Steps we took, in order
1. Checked the environment: Python 3.13, Playwright 1.63 with Chromium, pydantic, PyYAML,
   click and pytest were available. No network, so no new packages.
2. Chose Python (D-001), then wrote spec, dom, llm, healer, runner, planner and cli.
3. Built demo v1 and v2 and ran the example.
   - Result: v1 learned 4 selectors, and v2 healed all 4. It worked first time.
4. Found and fixed three bugs (below).
5. Wrote the test suite. Result: 15 passed in about 14s.
6. Wrote the README, this log and the decision log.

### Bugs found and how we fixed them
1. **Slow healing (12.5s on v2).** Each broken selector waited the full 3s timeout.
   Fix: wait for page load, then probe for 1.5s (D-009). Now about 6.6s.
2. **Assertion located by its own text.** The healed selector for the welcome message
   was `section:text-is("Welcome, asha!")`. That's circular, and it breaks if the name
   changes. Fix: never use text selectors for `expect_text`, and add a `role` option.
   Now `section[role="status"]`.
3. **False match (serious).** "the Delete account button" matched "Create account" on a
   first run, so a test that should fail passed. Fix: stricter threshold for intent-only
   matches (D-008), locked in by a regression test.

### Commands to see it work
```bash
V1="file://$PWD/examples/demo_site/v1/"
V2="file://$PWD/examples/demo_site/v2/"
cp examples/login_test.yaml /tmp/t.yaml
healwright run /tmp/t.yaml --base-url "$V1" --update   # learn selectors
healwright run /tmp/t.yaml --base-url "$V2"            # watch it heal
```

### Not done / known gaps
- The **real Anthropic API call has never run.** There was no network or key in the
  session. `plan` and LLM healing are only tested with `FakeProvider`.
- The name is not checked on PyPI or GitHub (D-002).
- No git commits yet.
- Tested only on two small local pages, not on real websites.

### Next steps (in priority order)
1. Put it on GitHub. Push and add a GitHub Actions workflow that runs `pytest`.
2. Test the LLM path for real: set `ANTHROPIC_API_KEY` and try `healwright plan "..." --url ... -o t.yaml`,
   then a heal where the heuristic gives up. Log the results here.
3. Try it on 2 or 3 real public demo sites (e.g. saucedemo.com, the-internet.herokuapp.com).
   Write down where healing fails, because that's the data for tuning.
4. Add an HTML heal report with a before/after table. It's great for the demo video.
5. Add `select` and `hover` actions.
6. Record the 2-minute demo video: v1 passes, the redesign breaks plain Playwright, and Healwright heals.

---

## Session 2: 2026-11-19, getting ready for GitHub

**Goal:** Put the project under version control, with tests running automatically on GitHub.

### What we did
1. Added `.github/workflows/tests.yml`. It installs the package and Chromium and runs
   `pytest` on Python 3.10 and 3.13, on every push to `main` and every pull request (D-013).
2. Checked that all code parses under Python 3.10, the oldest version CI tests.
3. Ran `git init` with `main` as the branch and made the first commit of everything (D-014).
4. Tried to push and got blocked: this workspace has no working GitHub login, and no
   GitHub account is linked to the Claude session. **Nothing has been pushed yet.**

### How to finish the push
**Option A, let Claude do it:**
1. Connect GitHub in claude.ai Settings → Connectors (GitHub).
2. Create an **empty** public repo named `healwright` on github.com, with no README,
   licence or .gitignore, because we already have them.
3. Tell Claude "push it". Claude attaches the repo and pushes `main`.

**Option B, do it yourself** (unzip the project and open a terminal in the folder):
```bash
git remote add origin https://github.com/<your-username>/healwright.git
git push -u origin main
```
Then open the repo's **Actions** tab and check the `tests` run goes green.

### Next steps
1. Finish the push (above), and confirm CI passes on GitHub.
2. Put your name in `LICENSE`, and add the CI badge to the top of the README:
   `![tests](https://github.com/<your-username>/healwright/actions/workflows/tests.yml/badge.svg)`
3. Then continue with Session 1's next steps, from step 2 on (live LLM test).

---

## Session 3: 2026-11-19, live on GitHub and free LLM support

**Goal:** Publish the repo, then test the AI features without paying.

### What we did
1. **Published:** the owner pushed to **github.com/HarshitMishra8/Healwright**, added their
   name to `LICENSE` and the CI badge to the README, and deleted the duplicate copies of
   the logs that had been put at the repo root. `docs/` is the only home for the logs.
   - Lesson: the first `git push` failed with "no upstream branch". That happens once per
     new branch, and `git push --set-upstream origin main` fixes it.
   - Lesson: the badge URL must match the repo name exactly, capital letters included
     (`Healwright`).
2. **Blocked on cost:** Anthropic API credits start at $5, too much for testing.
3. **Fix:** added free LLM options (D-015).
   - `healwright/llm.py`: added `OpenAICompatibleProvider`, `PRESETS` (gemini, ollama), and
     a new `default_provider()` that reads env vars and gives clear error messages.
   - `healwright/cli.py`: shows which provider and model are in use, and turns setup
     mistakes into one-line errors instead of crashes.
   - `tests/test_providers.py`: 7 new tests. One runs a tiny fake HTTP server on
     127.0.0.1 that pretends to be Gemini or Ollama, so the real HTTP code is tested with
     no internet. One runs a full LLM heal over HTTP.
   - README: new "Choosing an LLM" section.
4. Result: **22 tests pass.**

### How we checked Gemini details
We read Google's pricing page and OpenAI-compatibility page on 2026-11-19. The free models
include `gemini-3.8-flash`. The endpoint is
`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`, with the key
sent as `Authorization: Bearer`.

### Next steps
1. Apply this session's changes to your repo and push (`git am`, see chat). Check CI goes green.
2. **Live test with Gemini (free):**
   ```bash
   export GEMINI_API_KEY="..."       # from aistudio.google.com, never commit it
   healwright plan "Log in as asha with password s3cret, then check the welcome message says Welcome, asha!" --url login.html -o /tmp/ai_test.yaml
   healwright run /tmp/ai_test.yaml --base-url "file://$PWD/examples/demo_site/v1/" --update
   ```
   Then an LLM heal (intent "the primary action" on v2). Record the results here.
3. Optional: try Ollama locally and compare its quality with Gemini.

---

## Session 4: 2026-11-21, cleaning up authorship, first live AI call

**Goal:** Make Harshit the only contributor, then run the AI features for real with free Gemini.

### What happened, in order
1. **Contributors fix (D-016).** GitHub showed Claude as a contributor, because early
   commits used an AI git identity and "Co-Authored-By" lines. We rewrote history with
   `git filter-branch` (author, committer and message), checked with
   `git log --format='%h %an'`, and ran `git push --force`. Then we re-made the free-LLM
   patch under Harshit's name and applied it with `git am -3` and
   `git commit --amend --reset-author`.
2. **API key leaked in a screenshot.** The key was pasted *inside* the `read -s "..."`
   command instead of at its prompt. We deleted the key in AI Studio and created a new one.
   - Lesson: type the command, press Enter, and paste the key **only** when it asks. Never
     screenshot a terminal that shows a key. Clear the screen with `Cmd + K`.
3. **`dquote>` in zsh.** A `!` inside double quotes confuses zsh. Use single quotes:
   `healwright plan '... Welcome, asha!' ...`.
4. **Old code kept running** (`Set ANTHROPIC_API_KEY to use plan`). The tool had been
   installed as a *copy*, so the patch didn't reach it.
5. **`pip install -e .` broke on this Mac** (`ModuleNotFoundError: No module named 'healwright'`).
   macOS put the `hidden` flag on `.venv/.../__editable__...pth`, and Python 3.13+ ignores
   hidden `.pth` files. `chflags nohidden` didn't stick, probably because the project is on an
   iCloud-synced Desktop.
   - **Fix used:** a normal install, `pip install ".[dev]"`. **Re-run it after every code change
     or patch.** Fallback: `python -m healwright.cli ...` from the project folder.
   - Better long-term fix: move the project out of Desktop, e.g. to `~/code/healwright`.
6. **First live Gemini call reached Google, which returned HTTP 503 (busy).** The tool crashed
   with a traceback, so we added retries and readable errors (D-017). Tests: 27 passed.

7. **LIVE AI TEST PASSED ✅** (Gemini free tier, `gemini-3.5-flash-lite`, because 3.8-flash kept returning 503):
   | Test | Result |
   |---|---|
   | `plan`: one English sentence to a test | 5 correct steps (goto, fill username, fill password, click Log in, expect "Welcome, asha!"), intents only with no selectors, as D-003 requires |
   | `run` the AI-written test on v1 | **PASSED in 2.66s**. All 4 elements found by the free heuristic (confidence 1.0, 1.0, 1.0, 0.75). No LLM call needed |
   | LLM heal: "the primary action" on v2 | Heuristic gave up as intended. Gemini picked `button "Log in to Acme"` with **confidence 0.95**. **PASSED in 3.59s** |
   - This proves D-004 in real life: the cheap heuristic handles normal cases, and the LLM is only called for the hard one.

### Next steps
1. Apply the session 4 patch and run `pip install ".[dev]"` again.
2. README: add the tests badge on line 2, and change `<Harshit Mishra>` to `Harshit Mishra` in LICENSE.
3. Next feature: an HTML heal report (before/after), useful for the demo video.
4. Try it on a real public site (e.g. saucedemo.com).

### Housekeeping (2026-11-21)
- Added the tests badge to the README. Removed LICENSE: all rights reserved (D-018).
- Lesson: never `--amend` a pushed commit. It makes your copy and GitHub disagree, and
  `git push` is rejected. Fix used: `git fetch` + `git reset --hard origin/main`, then redo
  the change as a new commit.
- Lesson: patch files from chat must be downloaded first. These edits were applied with a
  pasted script instead.
