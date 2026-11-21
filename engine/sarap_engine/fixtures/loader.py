"""Load the vendored public-validation window. Coordinates stay local until impact.py."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PUBLIC_VALIDATION_FIXTURE = "fixture:public_validation_window"


def fixture_path() -> Path:
    return Path(__file__).resolve().parent / "public_validation_window.geojson"


@lru_cache(maxsize=1)
def fixture_collection() -> dict:
    return json.loads(fixture_path().read_text(encoding="utf-8"))
