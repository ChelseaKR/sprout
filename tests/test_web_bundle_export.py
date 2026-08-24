"""Tests for scripts/export_web_bundle.py (confidence fit propagation to web bundle)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sprout.config import ConfidenceFit, load_config

# Import helper from scripts/export_web_bundle.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from export_web_bundle import _export_config  # type: ignore[import-not-found]


def test_export_config_without_fit(tmp_path: Path) -> None:
    config_path = Path(__file__).resolve().parent.parent / "config" / "sprout.yaml"
    out_dir = tmp_path / "out"
    dest = _export_config(config_path, out_dir)
    assert dest.exists()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert "confidence" in data
    assert data["confidence"]["abstain_threshold"] == 0.25
    assert data["confidence"]["low_confidence_threshold"] == 0.50
    assert data["confidence"]["fit"] is None


def test_export_config_with_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = Path(__file__).resolve().parent.parent / "config" / "sprout.yaml"
    cfg = load_config(config_path)

    # Attach a mock ConfidenceFit
    fit = ConfidenceFit(
        midpoint=0.35,
        steepness=7.5,
        margin_bonus=0.08,
        train_dataset_hash="hash123",
        train_path="eval/train/calib.yaml",
        retrieval_config_hash="retrievalhash123",
        n_items=50,
        fitted_at="2026-08-23T00:00:00Z",
    )
    cfg_with_fit = cfg.model_copy(
        update={"confidence": cfg.confidence.model_copy(update={"fit": fit})}
    )

    import export_web_bundle

    monkeypatch.setattr(export_web_bundle, "load_config", lambda _: cfg_with_fit)

    out_dir = tmp_path / "out"
    dest = _export_config(config_path, out_dir)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["confidence"]["fit"] == {
        "midpoint": 0.35,
        "steepness": 7.5,
        "margin_bonus": 0.08,
    }
