"""Retrieval evaluation: recall@k and MRR against labelled questions, logged to MLflow.

Two experiments:

* ``index``  - the live AI Search index, comparing HYBRID, ANN and FULL_TEXT queries.
* ``chunks`` - chunking configs compared offline: each config is rebuilt from the
  landing Volume, embedded with the same model the index uses, and ranked by cosine
  similarity. This avoids building one AI Search index per config on Free Edition.

A retrieved chunk is relevant when its doc_id matches a label and its text contains
the label's evidence phrase, so labels work for any chunk size.

  uv run python -m careconnect.evals.retrieval --env dev
  uv run python -m careconnect.evals.retrieval --mode chunks --configs 400:60,200:40

Free Edition throttles direct calls to the embedding endpoint, so the chunking
experiment can instead embed on the laptop with an open model:

  uv run --with sentence-transformers python -m careconnect.evals.retrieval \\
      --mode chunks --embedder local
"""

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config
from careconnect.ingest.models import Chunk

KS = (1, 3, 5, 10)
QUERY_TYPES = ("HYBRID", "ANN", "FULL_TEXT", "AUTO")
DEFAULT_CONFIGS = "400:60,200:40,800:120"


@dataclass
class Label:
    doc_id: str
    evidence: str


@dataclass
class Question:
    id: str
    question: str
    relevant: list[Label]
    kind: str = "paraphrase"  # "exact": uses the document's own terms


# (doc_id, text) pairs in rank order, per question id
Rankings = dict[str, list[tuple[str, str]]]


def normalise(text: str) -> str:
    """Lowercase, drop markdown emphasis and curly quotes, collapse whitespace."""
    text = text.replace("*", "").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def load_questions(path: str | Path) -> list[Question]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [
        Question(
            q["id"],
            q["question"],
            [Label(**r) for r in q["relevant"]],
            q.get("kind", "paraphrase"),
        )
        for q in raw["questions"]
    ]


def is_relevant(q: Question, doc_id: str, text: str) -> bool:
    body = normalise(text)
    return any(lab.doc_id == doc_id and normalise(lab.evidence) in body for lab in q.relevant)


def answerable(questions: list[Question], chunks: list[Chunk]) -> tuple[list[Question], list[str]]:
    """Split questions into those with evidence in the corpus and the ids of those without."""
    ok, missing = [], []
    for q in questions:
        if any(is_relevant(q, c.doc_id, c.text) for c in chunks):
            ok.append(q)
        else:
            missing.append(q.id)
    return ok, missing


def score(questions: list[Question], rankings: Rankings, ks=KS) -> tuple[dict, list[dict]]:
    """Recall@k (share of questions with a relevant chunk in the top k), MRR and doc recall@5."""
    rows = []
    for q in questions:
        ranked = rankings.get(q.id, [])
        rank = next(
            (i for i, (doc_id, text) in enumerate(ranked, 1) if is_relevant(q, doc_id, text)), None
        )
        label_docs = {lab.doc_id for lab in q.relevant}
        rows.append(
            {
                "id": q.id,
                "kind": q.kind,
                "question": q.question,
                "first_relevant_rank": rank,
                "doc_hit_at_5": any(d in label_docs for d, _ in ranked[:5]),
                "top_docs": ", ".join(d for d, _ in ranked[:5]),
            }
        )
    n = len(rows) or 1
    metrics = {
        f"recall_at_{k}": sum(
            1 for r in rows if r["first_relevant_rank"] and r["first_relevant_rank"] <= k
        )
        / n
        for k in ks
    }
    metrics["mrr"] = sum(1 / r["first_relevant_rank"] for r in rows if r["first_relevant_rank"]) / n
    metrics["doc_recall_at_5"] = sum(r["doc_hit_at_5"] for r in rows) / n
    metrics["n_questions"] = len(rows)
    return metrics, rows


def score_by_kind(questions: list[Question], rankings: Rankings, ks=KS) -> dict[str, dict]:
    """The same metrics for each question kind (paraphrase, exact), keyed by kind."""
    kinds = sorted({q.kind for q in questions})
    return {
        kind: score([q for q in questions if q.kind == kind], rankings, ks)[0] for kind in kinds
    }


def with_kind_metrics(metrics: dict, by_kind: dict[str, dict]) -> dict:
    """Overall metrics plus per-kind ones prefixed with the kind, e.g. ``exact_mrr``."""
    out = dict(metrics)
    for kind, m in by_kind.items():
        out.update({f"{kind}_{name}": value for name, value in m.items()})
    return out


# ------------------------------------------------------------------ dense ranking


CACHE_DIR = Path.home() / ".cache" / "careconnect"


class EmbeddingCache:
    """Embeddings keyed by text hash, saved after every batch so a throttled run can resume.

    Lives outside the repo (in the user's home) so it is never committed.
    """

    def __init__(self, endpoint: str, cache_dir: Path = CACHE_DIR):
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / f"embeddings-{endpoint}.jsonl"
        self.vectors: dict[str, list[float]] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    self.vectors[rec["h"]] = rec["v"]

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def missing(self, texts: list[str]) -> list[str]:
        seen, out = set(), []
        for t in texts:
            h = self.key(t)
            if h not in self.vectors and h not in seen:
                seen.add(h)
                out.append(t)
        return out

    def add(self, texts: list[str], vectors: list[list[float]]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            for t, v in zip(texts, vectors, strict=True):
                h = self.key(t)
                self.vectors[h] = v
                f.write(json.dumps({"h": h, "v": v}) + "\n")

    def get(self, texts: list[str]) -> np.ndarray:
        arr = np.asarray([self.vectors[self.key(t)] for t in texts], dtype=np.float32)
        return arr / np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12, None)


class DatabricksEmbedder:
    """The embedding endpoint the index uses. Free Edition throttles direct calls hard."""

    query_prefix = ""

    def __init__(self, endpoint: str, w=None, max_attempts: int = 5, wait_s: float = 60):
        if w is None:
            from databricks.sdk import WorkspaceClient
            from databricks.sdk.core import Config

            # fail fast inside the SDK; we do our own, slower backoff below
            w = WorkspaceClient(config=Config(retry_timeout_seconds=30))
        self.w, self.endpoint, self.name = w, endpoint, endpoint
        self.max_attempts, self.wait_s = max_attempts, wait_s

    def encode(self, texts: list[str]) -> list[list[float]]:
        from databricks.sdk.errors import TooManyRequests

        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.w.serving_endpoints.query(name=self.endpoint, input=texts)
                return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
            except (TooManyRequests, TimeoutError):
                if attempt == self.max_attempts:
                    raise SystemExit(
                        f"{self.endpoint} is still rate limited after {attempt} attempts. "
                        "Progress is cached; re-run later, or use --embedder local."
                    ) from None
                wait = self.wait_s * attempt
                print(f"  rate limited; waiting {wait:.0f}s (attempt {attempt})")
                time.sleep(wait)
        raise AssertionError("unreachable")


class LocalEmbedder:
    """Open model run on the laptop: no rate limits, same model for every chunking config.

    Needs sentence-transformers (uv run --with sentence-transformers ...).
    """

    def __init__(self, model: str = "BAAI/bge-base-en-v1.5"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model)
        self.name = "local-" + model.split("/")[-1]
        # BGE models expect this instruction on queries (not on passages)
        self.query_prefix = (
            "Represent this sentence for searching relevant passages: " if "bge" in model else ""
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


def embed(
    embedder,
    texts: list[str],
    is_query: bool = False,
    batch_size: int = 64,
    pause_s: float = 2.0,
    cache: EmbeddingCache | None = None,
) -> np.ndarray:
    """Embed texts (L2-normalised rows), only encoding texts not already cached.

    Each batch is cached as soon as it returns, so an interrupted run resumes.
    """
    texts = [embedder.query_prefix + t for t in texts] if is_query else texts
    cache = cache or EmbeddingCache(embedder.name)
    todo = cache.missing(texts)
    if todo:
        print(
            f"  embedding {len(todo)} new texts with {embedder.name}"
            f" ({len(texts) - len(todo)} cached)"
        )
    for n, i in enumerate(range(0, len(todo), batch_size)):
        if n and pause_s:
            time.sleep(pause_s)
        batch = todo[i : i + batch_size]
        cache.add(batch, embedder.encode(batch))
        print(f"  {min(i + batch_size, len(todo))}/{len(todo)}")
    return cache.get(texts)


def dense_rankings(
    questions: list[Question], q_vecs: np.ndarray, chunks: list[Chunk], c_vecs: np.ndarray, k: int
) -> Rankings:
    sims = q_vecs @ c_vecs.T
    top = np.argsort(-sims, axis=1)[:, :k]
    return {
        q.id: [(chunks[j].doc_id, chunks[j].text) for j in top[i]] for i, q in enumerate(questions)
    }


def current_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Same population the index serves: superseded documents are filtered out."""
    return [c for c in chunks if c.status == "current"]


# ------------------------------------------------------------------ experiments


def run_index(cfg: ProjectConfig, questions: list[Question], k: int, query_type: str) -> Rankings:
    from careconnect.search.retriever import Retriever

    retriever = Retriever(cfg)
    return {
        q.id: [(h.doc_id, h.text) for h in retriever.search(q.question, k, query_type=query_type)]
        for q in questions
    }


def run_chunk_config(
    embedder, cfg: ProjectConfig, questions: list[Question], chunks: list[Chunk], q_vecs, k: int
) -> tuple[Rankings, dict]:
    pool = current_chunks(chunks)
    c_vecs = embed(embedder, [c.text for c in pool], pause_s=_pause(embedder))
    rankings = dense_rankings(questions, q_vecs, pool, c_vecs, k)
    tokens = sorted(c.token_count for c in pool)
    stats = {
        "n_chunks": len(pool),
        "median_chunk_tokens": tokens[len(tokens) // 2],
        # context cost: what an LLM would read for the top 5
        "mean_tokens_top5": float(
            np.mean([sum(_tokens(t) for _, t in r[:5]) for r in rankings.values()])
        ),
    }
    return rankings, stats


def _pause(embedder) -> float:
    return 2.0 if isinstance(embedder, DatabricksEmbedder) else 0.0


def _tokens(text: str) -> int:
    from careconnect.ingest.chunking import count_tokens

    return count_tokens(text)


# ------------------------------------------------------------------ MLflow


def experiment_path(w, name: str) -> str:
    """MLflow on Databricks needs a workspace path; relative names go under the user's home."""
    return name if name.startswith("/") else f"/Users/{w.current_user.me().user_name}/{name}"


def log_run(experiment: str, run_name: str, params: dict, metrics: dict, rows: list[dict]):
    import mlflow
    import pandas as pd

    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name):
        mlflow.set_tag("stage", "week2-retrieval-eval")
        mlflow.log_params(params)
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
        mlflow.log_table(pd.DataFrame(rows), artifact_file="per_question.json")


def _print_table(title: str, results: list[tuple[str, dict]]):
    cols = ["recall_at_1", "recall_at_3", "recall_at_5", "recall_at_10", "mrr", "doc_recall_at_5"]
    extra = [
        c for c in ("n_chunks", "median_chunk_tokens", "mean_tokens_top5") if c in results[0][1]
    ]
    print(f"\n{title}")
    print(f"{'run':<30}" + "".join(f"{c.replace('recall_at_', 'R@'):>10}" for c in cols + extra))
    for name, m in results:
        print(f"{name:<30}" + "".join(f"{m[c]:>10.3f}" for c in cols + extra))


def _find_questions() -> Path:
    return _find_config().parent / "data" / "eval" / "retrieval_questions.yml"


def main(argv: list[str] | None = None) -> None:
    from databricks.sdk import WorkspaceClient

    from careconnect.ingest.pipeline import build
    from careconnect.ingest.sources import SourceReader

    parser = argparse.ArgumentParser(description="Evaluate retrieval quality")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--questions", default=None)
    parser.add_argument("--mode", choices=["index", "chunks", "all"], default="all")
    parser.add_argument("--configs", default=DEFAULT_CONFIGS, help="max:overlap pairs")
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--source", default=None, help="default: landing Volume")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument(
        "--embedder",
        choices=["databricks", "local"],
        default="databricks",
        help="chunking experiment only; 'local' avoids Free Edition rate limits",
    )
    parser.add_argument("--local-model", default="BAAI/bge-base-en-v1.5")
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    w = WorkspaceClient()
    reader = SourceReader(args.source or cfg.landing_path)
    questions = load_questions(args.questions or _find_questions())

    # labels are checked against the production chunking so typos show up early
    base = build(reader, cfg.chunk_max_tokens, cfg.chunk_overlap_tokens).chunks
    questions, missing = answerable(questions, current_chunks(base))
    print(f"{len(questions)} questions with evidence in the corpus")
    if missing:
        print(f"WARNING: no chunk contains the evidence for {missing}; fix these labels")
    experiment = experiment_path(w, cfg.experiment_name)

    if args.mode in ("index", "all"):
        results, kind_results = [], []
        for qt in QUERY_TYPES:
            rankings = run_index(cfg, questions, args.k, qt)
            metrics, rows = score(questions, rankings)
            by_kind = score_by_kind(questions, rankings)
            results.append((qt, metrics))
            kind_results += [
                (f"{qt} {kind} (n={m['n_questions']})", m) for kind, m in by_kind.items()
            ]
            metrics = with_kind_metrics(metrics, by_kind)
            if not args.no_mlflow:
                params = {
                    "experiment": "index",
                    "query_type": qt,
                    "k": args.k,
                    "index": cfg.chunks_index,
                    "chunking": f"{cfg.chunk_max_tokens}:{cfg.chunk_overlap_tokens}",
                }
                log_run(experiment, f"index-{qt.lower()}", params, metrics, rows)
        _print_table("Live AI Search index (query types)", results)
        if len({q.kind for q in questions}) > 1:
            _print_table("By question kind", sorted(kind_results, key=lambda r: r[0].split()[1]))

    if args.mode in ("chunks", "all"):
        if args.embedder == "local":
            embedder = LocalEmbedder(args.local_model)
        else:
            embedder = DatabricksEmbedder(cfg.embedding_endpoint)
        q_vecs = embed(
            embedder, [q.question for q in questions], is_query=True, pause_s=_pause(embedder)
        )
        results = []
        for pair in args.configs.split(","):
            max_t, overlap = (int(x) for x in pair.split(":"))
            chunks = build(reader, max_t, overlap).chunks
            rankings, stats = run_chunk_config(embedder, cfg, questions, chunks, q_vecs, args.k)
            metrics, rows = score(questions, rankings)
            metrics = with_kind_metrics(metrics, score_by_kind(questions, rankings))
            metrics.update(stats)
            results.append((f"dense {max_t}/{overlap}", metrics))
            if not args.no_mlflow:
                params = {
                    "experiment": "chunking",
                    "max_tokens": max_t,
                    "overlap_tokens": overlap,
                    "k": args.k,
                    "embedding": embedder.name,
                }
                log_run(experiment, f"chunks-{max_t}-{overlap}", params, metrics, rows)
        _print_table(f"Chunking configs (dense retrieval, {embedder.name})", results)

    if not args.no_mlflow:
        print(f"\nLogged to MLflow experiment {experiment}")


if __name__ == "__main__":
    main()
