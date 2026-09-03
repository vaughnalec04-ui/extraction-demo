"""End-to-end against the committed cache.

The README says the evaluation replays from the committed cache with no API
key and reproduces the committed results.json. This tests that.
"""
import json
import os
import sys

import pytest

from meridian import settings
from meridian.harness import run


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_committed_cache_covers_the_full_test_split():
    assert run.available_runs("test") >= 1
    cov = run.scorable_docs("test", 1)
    assert cov["n_scored"] == cov["n_total"] == 40
    assert cov["excluded"] == []


def test_scoring_is_deterministic():
    labels = run.load_labels()
    a = run.score("double_key", "test", 1, 0.0, 0.0, labels)
    b = run.score("double_key", "test", 1, 0.0, 0.0, labels)
    assert a == b


def test_evaluate_reproduces_committed_results(tmp_path, monkeypatch, capsys):
    out = tmp_path / "results.json"
    monkeypatch.setattr(sys, "argv", ["evaluate", "--split", "test", "--runs", "1", "--out", str(out)])
    run.main()
    printed = capsys.readouterr().out

    fresh = json.load(open(out))
    committed = json.load(open(os.path.join(settings.RESULTS, "results.json")))

    # Every charted number matches what is committed.
    assert fresh["frontier"] == committed["frontier"]
    assert fresh["configs"] == committed["configs"]
    assert fresh["meta"]["documents_scored"] == 40
    # Nothing excluded, so no exclusion reason.
    assert fresh["meta"]["documents_excluded"] == []
    assert fresh["meta"]["exclusion_reason"] is None
    # The terminal demo shows the headline sections.
    assert "COST / ACCURACY FRONTIER" in printed
    assert "RECONCILIATION" in printed
    assert "n/a" in printed            # 0/0 abstention precision shown as undefined


def test_extra_runs_requested_degrades_gracefully(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evaluate", "--split", "test", "--runs", "99",
                                      "--out", str(tmp_path / "r.json")])
    run.main()
    assert "99 run(s) requested but only" in capsys.readouterr().out


def test_thresholds_tuned_on_tune_split():
    with open(os.path.join(settings.CONFIG, "thresholds.json")) as fh:
        t = json.load(fh)
    assert "tune" in t["tuned_on"] and "never test" in t["tuned_on"]
    assert set(t["chosen"]) == set(run.CONFIGS)
