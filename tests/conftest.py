import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo_site"


@pytest.fixture
def v1_url() -> str:
    return (DEMO / "v1").as_uri() + "/"


@pytest.fixture
def v2_url() -> str:
    return (DEMO / "v2").as_uri() + "/"


@pytest.fixture
def login_spec(tmp_path) -> Path:
    """A fresh copy of the example spec (no selectors yet)."""
    dst = tmp_path / "login_test.yaml"
    shutil.copy(ROOT / "examples" / "login_test.yaml", dst)
    return dst
