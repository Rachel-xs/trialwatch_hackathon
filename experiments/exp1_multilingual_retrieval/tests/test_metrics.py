"""Metric sanity tests — hand-computed expectations."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fairtrial.corpus import Doc, build_chunk_plan, plan_chunks
from fairtrial.index import Hit
from fairtrial.metrics import paired_bootstrap, per_query_metrics


def hit(rank: int, doc_id: str, para_ids: list[str]) -> Hit:
    return Hit(rank=rank, chunk_id=f"{doc_id}#c{rank:03d}", doc_id=doc_id, lang="id", para_ids=para_ids, score=1.0 / rank)


def test_metrics_basic():
    hits = [
        hit(1, "id-002", ["id-002#p001", "id-002#p002"]),
        hit(2, "id-001", ["id-001#p004", "id-001#p005"]),
        hit(3, "tr-007", ["tr-007#p001"]),
    ]
    gold = {"relevant_docs": ["id-001"], "evidence": ["id-001#p004", "id-001#p009"]}
    m = per_query_metrics(hits, gold, ks=[1, 3])

    assert m["hit@1"] == 0.0 and m["hit@3"] == 1.0
    assert m["mrr@1"] == 0.0 and m["mrr@3"] == 0.5          # first relevant chunk at rank 2
    assert m["recall_doc@3"] == 1.0                          # 1 of 1 relevant doc found
    assert m["evidence_recall@3"] == 0.5                     # p004 found, p009 not
    assert m["evidence_recall@1"] == 0.0


def test_evidence_undefined_without_annotation():
    hits = [hit(1, "id-001", ["id-001#p001"])]
    m = per_query_metrics(hits, {"relevant_docs": ["id-001"], "evidence": []}, ks=[1])
    assert m["evidence_recall@1"] is None
    assert m["hit@1"] == 1.0


def test_multi_doc_recall():
    hits = [hit(1, "id-001", []), hit(2, "tr-002", [])]
    gold = {"relevant_docs": ["id-001", "tr-002", "tr-003"]}
    m = per_query_metrics(hits, gold, ks=[2])
    assert abs(m["recall_doc@2"] - 2 / 3) < 1e-9
    assert m["mrr@2"] == 1.0


def test_chunk_plan_is_language_independent():
    """The same plan must apply to a translation of different length."""
    src = Doc(doc_id="id-001", lang="id", paragraphs=["a" * 400, "b" * 400, "c" * 400, "d" * 50])
    plan = plan_chunks(src, max_chars=900, min_chars=200)
    assert [spec.para_indices for spec in plan] == [[0, 1], [2, 3]]
    # Rendering against English paragraphs of wildly different lengths uses the
    # identical paragraph grouping, so chunk IDs stay comparable across pipelines.
    english = ["x" * 50, "y" * 900, "z" * 10, "w" * 600]
    assert plan[0].render(english).startswith("x")
    assert plan[0].para_ids == ["id-001#p001", "id-001#p002"]


def test_long_paragraph_not_split():
    src = Doc(doc_id="tr-001", lang="tr", paragraphs=["x" * 3000, "y" * 300])
    plan = plan_chunks(src, max_chars=900, min_chars=200)
    assert plan[0].para_indices == [0]
    assert plan[1].para_indices == [1]


def test_paired_bootstrap_detects_consistent_win():
    a = [0.0] * 20
    b = [1.0] * 20
    stats = paired_bootstrap(a, b, samples=2000, seed=1)
    assert stats["delta"] == 1.0
    assert stats["ci_low"] > 0.5
    assert stats["p_value"] < 0.05


def test_paired_bootstrap_no_effect():
    a = [1.0, 0.0] * 10
    b = [0.0, 1.0] * 10
    stats = paired_bootstrap(a, b, samples=2000, seed=1)
    assert abs(stats["delta"]) < 1e-9
    assert stats["ci_low"] < 0 < stats["ci_high"]


def test_build_chunk_plan_covers_every_paragraph():
    docs = [
        Doc(doc_id="id-001", lang="id", paragraphs=["p" * 300 for _ in range(7)]),
        Doc(doc_id="tr-001", lang="tr", paragraphs=["q" * 120 for _ in range(4)]),
    ]
    plan = build_chunk_plan(docs, max_chars=900, min_chars=200)
    for doc in docs:
        covered = sorted(i for spec in plan if spec.doc_id == doc.doc_id for i in spec.para_indices)
        assert covered == list(range(len(doc.paragraphs))), doc.doc_id
