"""Locate data bundled inside the installed package.

So ``pipx install sprout && sprout ingest && sprout ask "..."`` works with no checkout:
the corpus and a default config ship under ``sprout/data/``. A local file in the working
directory always wins (for development and adopters), and only when it is absent do we fall
back to the packaged copy.
"""

from __future__ import annotations

from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"


def data_dir() -> Path:
    return _DATA


def packaged_config() -> Path:
    """Path to the bundled default ``sprout.yaml``."""
    return _DATA / "sprout.yaml"


def locate(path: str | Path) -> Path:
    """Return ``path`` if it exists in the CWD, else the packaged copy, else ``path``.

    Returning the original path when neither exists lets the caller raise its normal,
    informative not-found error.
    """
    p = Path(path)
    if p.exists():
        return p
    bundled = _DATA / path
    return bundled if bundled.exists() else p
