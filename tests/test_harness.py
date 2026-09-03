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


def test_harness_refuses_a_cached_response_for_a_changed_image(tmp_path, monkeypatch):
    """The scoring path checks freshness too. A regenerated corpus must not be
    scored against the old responses."""
    import shutil
    doc = json.load(open(os.path.join(settings.DATA, "splits.json")))["test"][0]
    docs = tmp_path / "docs"
    docs.mkdir()
    dst = docs / (doc + settings.DOC_EXT)
    shutil.copy(os.path.join(settings.DOCS, doc + settings.DOC_EXT), dst)
    with open(dst, "ab") as fh:
        fh.write(b"\x00")                      # one byte: a different image
    monkeypatch.setattr(run, "DOCS", str(docs))
    with pytest.raises(SystemExit, match="Stale cached response"):
        run.load_cache(settings.PRIMARY, "test", 1, [doc])
    monkeypatch.setattr(run, "DOCS", settings.DOCS)
    assert doc in run.load_cache(settings.PRIMARY, "test", 1, [doc])


def test_failed_and_unparseable_calls_are_excluded_by_name(tmp_path, monkeypatch):
    ids = json.load(open(os.path.join(settings.DATA, "splits.json")))["test"]
    good, failed, garbled = ids[0], ids[1], ids[2]
    for model in (settings.PRIMARY, settings.VERIFIER):
        d = tmp_path / model / "test-run1"
        d.mkdir(parents=True)
        (d / (good + ".json")).write_text(json.dumps({"error": None, "response": {"x": 1}}))
        (d / (failed + ".json")).write_text(json.dumps({"error": "ClientError: 503", "response": None}))
        (d / (garbled + ".json")).write_text(json.dumps({"error": None, "response": None}))
    monkeypatch.setattr(run, "CACHE", str(tmp_path))
    cov = run.scorable_docs("test", 1)
    assert cov["scored"] == [good]
    assert failed in cov["excluded"] and garbled in cov["excluded"]
    assert cov["n_scored"] == 1 and cov["n_total"] == len(ids)


def test_tune_only_ever_scores_the_tune_split(monkeypatch):
    seen = []

    def fake_score(config, split, run_idx, tau_a, tau_e, labels, doc_ids=None):
        seen.append(split)
        return {"overall": {"coverage": {"point": 1.0},
                            "normalized_match_on_covered": {"point": 1.0},
                            "abstention_precision": {"point": None}},
                "cost": {"mean_usd_per_doc": 0.001}, "escalation_rate": 0.0}

    monkeypatch.setattr(run, "score", fake_score)
    out = run.tune(run.load_labels())
    assert seen and set(seen) == {"tune"}
    assert out["tuned_on"].startswith("tune split")
