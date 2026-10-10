from pathlib import Path

import numpy as np

from careconnect.evals.retrieval import (
    Label,
    Question,
    answerable,
    current_chunks,
    dense_rankings,
    load_questions,
    normalise,
    score,
    score_by_kind,
    with_kind_metrics,
)
from careconnect.ingest.pipeline import build
from careconnect.ingest.sources import SourceReader

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data" / "eval" / "retrieval_questions.yml"

Q = Question("q", "?", [Label("d1", "Six **months**")])


def test_normalise_ignores_markdown_case_and_spacing():
    assert normalise("Within **6  months**\nof the event") == "within 6 months of the event"


def test_score_recall_and_mrr():
    rankings = {
        "a": [("x", "no"), ("d1", "within six months here")],  # relevant at rank 2
        "b": [("x", "no"), ("y", "no")],  # miss
    }
    qa = Question("a", "?", [Label("d1", "six months")])
    qb = Question("b", "?", [Label("d1", "six months")])
    metrics, rows = score([qa, qb], rankings, ks=(1, 3))
    assert metrics["recall_at_1"] == 0
    assert metrics["recall_at_3"] == 0.5
    assert metrics["mrr"] == 0.25
    assert rows[0]["first_relevant_rank"] == 2


def test_relevance_needs_the_right_document():
    metrics, _ = score([Q], {"q": [("other-doc", "six months")]}, ks=(1,))
    assert metrics["recall_at_1"] == 0
    assert metrics["doc_recall_at_5"] == 0


def test_dense_rankings_orders_by_cosine():
    chunks = [
        type("C", (), {"doc_id": "a", "text": "A"})(),
        type("C", (), {"doc_id": "b", "text": "B"})(),
    ]
    q_vecs = np.array([[0.0, 1.0]])
    c_vecs = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert dense_rankings([Q], q_vecs, chunks, c_vecs, k=2)["q"][0][0] == "b"


def test_question_ids_are_unique_and_labelled():
    questions = load_questions(QUESTIONS)
    assert len(questions) >= 40
    assert len({q.id for q in questions}) == len(questions)
    assert all(q.relevant for q in questions)


def test_score_by_kind_splits_paraphrase_and_exact():
    qa = Question("a", "?", [Label("d1", "six months")])  # paraphrase by default
    qb = Question("b", "?", [Label("d1", "six months")], kind="exact")
    rankings = {"a": [("d1", "six months")], "b": [("x", "no"), ("d1", "six months")]}
    by_kind = score_by_kind([qa, qb], rankings, ks=(1,))
    assert by_kind["paraphrase"]["mrr"] == 1.0
    assert by_kind["exact"]["mrr"] == 0.5
    combined = with_kind_metrics({"mrr": 0.75}, by_kind)
    assert combined["mrr"] == 0.75
    assert combined["exact_mrr"] == 0.5
    assert combined["exact_n_questions"] == 1


def test_question_kinds_are_known():
    questions = load_questions(QUESTIONS)
    assert {q.kind for q in questions} <= {"paraphrase", "exact"}
    assert sum(q.kind == "exact" for q in questions) >= 10


def test_every_leaflet_label_has_evidence_in_its_leaflet():
    # policy PDFs are not in git, so only leaflet labels can be checked here
    chunks = current_chunks(build(SourceReader(str(ROOT / "data" / "raw")), 400, 60).chunks)
    questions = load_questions(QUESTIONS)
    for q in questions:
        for lab in q.relevant:
            if lab.doc_id.startswith("fvhb-"):
                single = Question(q.id, q.question, [lab])
                assert answerable([single], chunks)[0], (
                    f"{q.id}: '{lab.evidence}' not in {lab.doc_id}"
                )


def test_embed_only_encodes_uncached_texts(tmp_path):
    from careconnect.evals.retrieval import EmbeddingCache, embed

    class Fake:
        name, query_prefix = "fake", "q: "

        def __init__(self):
            self.calls = []

        def encode(self, texts):
            self.calls.append(list(texts))
            return [[float(len(t)), 1.0] for t in texts]

    fake = Fake()
    first = embed(
        fake, ["a", "bb", "a"], batch_size=1, pause_s=0, cache=EmbeddingCache("f", tmp_path)
    )
    assert first.shape == (3, 2)
    assert fake.calls == [["a"], ["bb"]]  # duplicate text encoded once

    # a new cache object reads the saved file: no further calls
    embed(fake, ["bb", "a"], pause_s=0, cache=EmbeddingCache("f", tmp_path))
    assert len(fake.calls) == 2

    # queries get the model's prefix, so they are cached separately from passages
    embed(fake, ["a"], is_query=True, pause_s=0, cache=EmbeddingCache("f", tmp_path))
    assert fake.calls[-1] == ["q: a"]


def test_databricks_embedder_backs_off_then_succeeds(monkeypatch):
    from types import SimpleNamespace as NS

    from databricks.sdk.errors import TooManyRequests

    from careconnect.evals import retrieval

    monkeypatch.setattr(retrieval.time, "sleep", lambda s: None)
    attempts = []

    def query(name, input):
        attempts.append(1)
        if len(attempts) < 3:
            raise TooManyRequests("limit")
        return NS(data=[NS(index=0, embedding=[1.0, 0.0])])

    emb = retrieval.DatabricksEmbedder("ep", w=NS(serving_endpoints=NS(query=query)))
    assert emb.encode(["x"]) == [[1.0, 0.0]]
    assert len(attempts) == 3
