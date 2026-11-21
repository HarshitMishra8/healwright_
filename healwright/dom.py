"""Reading elements off the page: fingerprints, candidates, and stable selectors.

A *fingerprint* is a small dict of an element's attributes (tag, id, text,
label, placeholder ...). We save it after every successful step so that, when
the selector later breaks, we know what the element used to look like.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page

# JavaScript helpers injected into the page. Kept as one string so the same
# fingerprint logic is used for "the element we just used" and "candidates".
_JS_HELPERS = r"""
const __hw_clean = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, 120);
function __hw_fp(el) {
  const tag = el.tagName.toLowerCase();
  const isBtnInput = tag === 'input' && ['submit', 'button', 'reset'].includes((el.type || '').toLowerCase());
  const text = tag === 'input' ? (isBtnInput ? el.value : '') : el.innerText;
  const labels = el.labels ? Array.from(el.labels).map(l => __hw_clean(l.innerText)).join(' ') : '';
  return {
    tag,
    id: el.id || '',
    name: el.getAttribute('name') || '',
    type: (el.getAttribute('type') || '').toLowerCase(),
    text: __hw_clean(text),
    aria_label: el.getAttribute('aria-label') || '',
    placeholder: el.getAttribute('placeholder') || '',
    role: el.getAttribute('role') || '',
    testid: el.getAttribute('data-testid') || '',
    classes: __hw_clean(el.getAttribute('class')),
    href: el.getAttribute('href') || '',
    label: labels,
  };
}
function __hw_path(el) {
  const parts = [];
  while (el && el.nodeType === 1 && el !== document.documentElement) {
    let s = el.tagName.toLowerCase();
    if (el.id) { parts.unshift(s + '#' + CSS.escape(el.id)); break; }
    let i = 1, sib = el;
    while ((sib = sib.previousElementSibling)) if (sib.tagName === el.tagName) i++;
    parts.unshift(s + ':nth-of-type(' + i + ')');
    el = el.parentElement;
  }
  return parts.join(' > ');
}
function __hw_visible(el) {
  const r = el.getBoundingClientRect();
  const st = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
}
"""

# Which elements are worth considering for each action.
CANDIDATE_SELECTORS = {
    "fill": (
        "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox])"
        ":not([type=radio]):not([type=reset]), textarea, [contenteditable=true]"
    ),
    "click": (
        "button, a, input[type=submit], input[type=button], input[type=checkbox], input[type=radio], "
        "[role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], select, summary, label"
    ),
    "expect_text": "body *",
    "expect_visible": "body *",
}

MAX_CANDIDATES = 300


def fingerprint(page: Page, selector: str) -> dict:
    """Fingerprint the single element matched by ``selector``."""
    return page.locator(selector).evaluate(f"(el) => {{ {_JS_HELPERS} return __hw_fp(el); }}")


def candidates(page: Page, action: str, must_contain: str | None = None) -> list[dict]:
    """List visible elements that could be the target of ``action``.

    Each candidate is a fingerprint plus a ``path`` (a CSS path that is always
    unique) we can fall back to. For ``expect_text`` only the deepest elements
    whose text contains ``must_contain`` are returned.
    """
    css = CANDIDATE_SELECTORS[action]
    script = f"""([css, mustContain, max]) => {{
      {_JS_HELPERS}
      let els = Array.from(document.querySelectorAll(css)).filter(__hw_visible);
      if (mustContain) {{
        const needle = mustContain.toLowerCase();
        const has = e => (e.innerText || '').toLowerCase().includes(needle);
        els = els.filter(e => has(e) && !Array.from(e.children).some(has));
      }}
      return els.slice(0, max).map(e => Object.assign(__hw_fp(e), {{ path: __hw_path(e) }}));
    }}"""
    return page.evaluate(script, [css, must_contain, MAX_CANDIDATES])


def _q(s: str) -> str:
    return json.dumps(s)  # safe double-quoted string for selectors


def selector_options(c: dict, action: str | None = None) -> list[str]:
    """Selectors for a candidate, most stable first (see DECISIONS D-005).

    For expect_text we never select by text: the text is what we are checking,
    and it is often dynamic ("Welcome, asha!").
    """
    tag = c["tag"]
    opts = []
    if c.get("testid"):
        opts.append(f"[data-testid={_q(c['testid'])}]")
    if c.get("id") and not any(ch.isdigit() for ch in c["id"][-4:]):  # skip auto-generated-looking ids
        opts.append(f"{tag}[id={_q(c['id'])}]")
    if c.get("name"):
        opts.append(f"{tag}[name={_q(c['name'])}]")
    if c.get("aria_label"):
        opts.append(f"{tag}[aria-label={_q(c['aria_label'])}]")
    if c.get("placeholder"):
        opts.append(f"{tag}[placeholder={_q(c['placeholder'])}]")
    if c.get("role"):
        opts.append(f"{tag}[role={_q(c['role'])}]")
    if c.get("text") and len(c["text"]) <= 60 and tag != "input" and action != "expect_text":
        opts.append(f"{tag}:text-is({_q(c['text'])})")
    opts.append(c["path"])
    return opts


def best_selector(page: Page, c: dict, action: str | None = None) -> str:
    """First selector option that matches exactly one element on the page."""
    for sel in selector_options(c, action):
        try:
            if page.locator(sel).count() == 1:
                return sel
        except Exception:  # invalid selector for this engine; try the next
            continue
    return c["path"]
