"""Resource root resolver supporting both source checkouts and standalone wheels (`uvx`)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_resource_root() -> Path:
    """Return repo root in source checkouts, or `opf/_bundled` inside installed wheels."""
    if (REPO_ROOT / "dictionaries").is_dir() and (REPO_ROOT / "spec" / "schema").is_dir():
        return REPO_ROOT
    return Path(__file__).resolve().parent / "_bundled"
