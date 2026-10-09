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
