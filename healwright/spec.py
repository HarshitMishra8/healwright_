"""Test spec format: a YAML file of plain-English steps.

Each step says WHAT to do (``intent``) in human words. The ``selector`` and
``fingerprint`` are filled in by Healwright the first time the step runs with
``--update``, and refreshed when a step is healed. See docs/DECISIONS.md D-003.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

Action = Literal["goto", "click", "fill", "expect_text", "expect_visible"]

# Actions that act on a page element (everything except goto).
ELEMENT_ACTIONS = {"click", "fill", "expect_text", "expect_visible"}


class Step(BaseModel):
    action: Action
    intent: str = Field(..., description="Plain-English description of the step")
    value: Optional[str] = Field(None, description="URL for goto, text for fill/expect_text")
    selector: Optional[str] = Field(None, description="Last known working selector (auto-managed)")
    fingerprint: Optional[dict] = Field(None, description="Element attributes from the last good run (auto-managed)")


class TestSpec(BaseModel):
    __test__ = False  # tell pytest this is not a test class
    name: str
    base_url: Optional[str] = None
    steps: list[Step]

    @classmethod
    def load(cls, path: str | Path) -> "TestSpec":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def save(self, path: str | Path) -> None:
        data = self.model_dump(exclude_none=True)
        Path(path).write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
