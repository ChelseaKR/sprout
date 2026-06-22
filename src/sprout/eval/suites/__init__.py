"""Importing this package registers all built-in suites into the suite registry.

New suites can also be contributed by third parties through the ``sprout.eval.suites``
entry-point group; importing here covers the in-tree ones.
"""

from __future__ import annotations

from . import calibration, groundedness, multilingual, refusal, safety

__all__ = ["calibration", "groundedness", "multilingual", "refusal", "safety"]
