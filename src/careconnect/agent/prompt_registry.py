"""The agent's system prompt in the MLflow Prompt Registry (Unity Catalog), with a gated alias.

  uv run python -m careconnect.agent.prompt_registry --env dev show
  uv run python -m careconnect.agent.prompt_registry --env dev register --set-production  # 1st
  uv run python -m careconnect.agent.prompt_registry --env dev register -m "why it changed"
  uv run python -m careconnect.agent.prompt_registry --env dev register --file new_prompt.txt
  uv run python -m careconnect.agent.prompt_registry --env dev promote --candidate 2
  uv run python -m careconnect.agent.prompt_registry --env dev promote --candidate 2 --dry-run
  uv run python -m careconnect.agent.prompt_registry --env dev rollback

How it works:
* Every wording is a numbered, immutable version of <catalog>.<schema>.careconnect_agent_prompt.
* The agent uses whichever version the alias "production" points to. If the registry cannot
  be reached it falls back to SYSTEM_PROMPT in prompts.py, so answers never stop.
* The alias only moves through `promote`: the evaluation runs N times (default 3) with the
  production version and N times with the candidate, and the candidate wins only if its
  worst run is at least as good as production's worst run on pass rate, safety and
  violations, and it never misses an urgent case (see `decide`). If any run had failed or
  retried tool calls or was abnormally slow (`HEALTH_LIMITS`), the result is INCONCLUSIVE and
  nothing moves: those scores measure the platform, not the prompt. The old version keeps the
  alias "previous", so `rollback` is one command.
"""

import argparse
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import mlflow

from careconnect.agent.prompts import SYSTEM_PROMPT
from careconnect.agent.tracing import prompt_hash
from careconnect.config import ProjectConfig

PRODUCTION = "production"
PREVIOUS = "previous"

# (metric, True if higher is better). The candidate's worst run must match production's.
GATE_METRICS = [
    ("pass_rate", True),
    ("urgent_recall", True),
    ("false_alarm_rate", False),
    ("violation_rate", False),
]


# A run is only evidence about the prompt if the platform was healthy while it ran. On 18 Oct
# slow tool lookups spoilt runs of both versions (22 to 51 s per question, standard refusals);
# a healthy run on 19 Oct took 5.5 s with no tool errors or retries.
HEALTH_LIMITS = {"tool_errors": 0, "tool_retries": 2, "mean_seconds": 15.0}


def health_problems(runs: list[dict], labels: list[str] | None = None) -> list[str]:
    """Why these evaluation runs cannot be trusted to compare prompts; [] if they can."""
    problems = []
    for i, r in enumerate(runs):
        name = labels[i] if labels else f"run {i + 1}"
        for metric, limit in HEALTH_LIMITS.items():
            value = r.get(metric)
            if value is not None and value > limit:
                problems.append(f"{name}: {metric} {value:g} (limit {limit:g})")
    return problems


@dataclass(frozen=True)
class LoadedPrompt:
    text: str
    version: str  # registry version number as text, or "code"
    source: str  # "registry" or "code"
    note: str = ""  # why the code copy was used, if it was

    @property
    def hash(self) -> str:
        return prompt_hash(self.text)

    def describe(self) -> str:
        if self.source == "registry":
            return f"version {self.version} from the Prompt Registry (hash {self.hash})"
        return f"the copy in prompts.py (hash {self.hash}): {self.note}"


def _use_unity_catalog() -> None:
    if mlflow.get_tracking_uri() != "databricks":  # keep an experiment already set up
        mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")  # prompts live in Unity Catalog


def _uri(cfg: ProjectConfig, ref: str) -> str:
    """prompts:/name/2 for a version number, prompts:/name@production for an alias."""
    ref = str(ref)
    return (
        f"prompts:/{cfg.agent_prompt}/{ref}"
        if ref.isdigit()
        else f"prompts:/{cfg.agent_prompt}@{ref}"
    )


def load_system_prompt(cfg: ProjectConfig, ref: str = PRODUCTION, strict: bool = False):
    """The prompt for `ref` (an alias or a version number).

    strict=False (the agent): any registry problem falls back to the copy in prompts.py.
    strict=True (promotion, or an explicitly requested version): errors are raised.
    """
    try:
        _use_unity_catalog()
        pv = mlflow.genai.load_prompt(_uri(cfg, ref), link_to_model=False)
        return LoadedPrompt(pv.template, str(pv.version), "registry")
    except Exception as exc:  # noqa: BLE001 - never let the registry stop an answer
        if strict:
            raise
        reason = " ".join(str(exc).split())[:160]
        return LoadedPrompt(SYSTEM_PROMPT, "code", "code", f"registry unavailable ({reason})")


def _versions(cfg: ProjectConfig) -> list:
    """All versions of the prompt, oldest first; [] if they cannot be listed."""
    try:
        res = mlflow.MlflowClient().search_prompt_versions(cfg.agent_prompt)
    except Exception:  # noqa: BLE001 - listing is a convenience, not a requirement
        return []
    versions = list(getattr(res, "prompt_versions", res) or [])
    return sorted(versions, key=lambda v: int(v.version))


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def register(cfg: ProjectConfig, text: str, message: str, source: str) -> tuple[str, bool]:
    """Register `text` as a new version unless an identical one exists. Returns (version, new)."""
    _use_unity_catalog()
    digest = prompt_hash(text)
    for v in _versions(cfg):
        if v.template == text:
            return str(v.version), False
    pv = mlflow.genai.register_prompt(
        name=cfg.agent_prompt,
        template=text,
        commit_message=message,
        tags={"prompt_hash": digest, "source": source, "git_commit": _git_commit()},
    )
    return str(pv.version), True


def alias_version(cfg: ProjectConfig, alias: str) -> str | None:
    try:
        _use_unity_catalog()
        return str(
            mlflow.MlflowClient().get_prompt_version_by_alias(cfg.agent_prompt, alias).version
        )
    except Exception:  # noqa: BLE001 - no such alias (yet)
        return None


def set_alias(cfg: ProjectConfig, alias: str, version: str) -> None:
    _use_unity_catalog()
    mlflow.genai.set_prompt_alias(cfg.agent_prompt, alias=alias, version=int(version))


def decide(production: list[dict], candidate: list[dict]) -> tuple[bool, list[str]]:
    """The promotion gate, on the metrics of each evaluation run.

    The candidate's worst run must be at least as good as production's worst run on every
    gate metric, and every candidate run must catch every urgent case. Returns (promote,
    reasons), one reason line per check.
    """
    if not production or not candidate:
        return False, ["no evaluation runs to compare"]
    if {r["n_cases"] for r in production} != {r["n_cases"] for r in candidate}:
        return False, ["the runs did not use the same number of questions"]
    ok, reasons = True, []
    for metric, higher_is_better in GATE_METRICS:
        worst = min if higher_is_better else max
        prod, cand = worst(r[metric] for r in production), worst(r[metric] for r in candidate)
        passed = cand >= prod if higher_is_better else cand <= prod
        ok &= passed
        sign = (">=" if passed else "<") if higher_is_better else ("<=" if passed else ">")
        reasons.append(
            f"{'ok  ' if passed else 'FAIL'} {metric}: candidate worst {cand:.3f} {sign} "
            f"production worst {prod:.3f}"
        )
    missed = [r["urgent_recall"] for r in candidate if r["urgent_recall"] < 1.0]
    if missed:
        ok = False
        reasons.append(f"FAIL urgent cases missed in {len(missed)} candidate run(s)")
    else:
        reasons.append("ok   every candidate run caught every urgent case")
    return ok, reasons


# ------------------------------------------------------------------ command line


def _evaluate(cfg, prompt: LoadedPrompt, label: str, runs: int, backend: str, cases) -> list:
    from careconnect.agent.main import build_agent
    from careconnect.evals.agent import evaluate

    agent = build_agent(cfg, backend=backend, prompt=prompt)
    results = []
    for i in range(1, runs + 1):
        eval_run = f"{backend}-{time.strftime('%Y%m%d-%H%M%S')}-v{prompt.version}-r{i}"
        print(f"\n{label} (version {prompt.version}), run {i} of {runs}   eval_run: {eval_run}")
        metrics = evaluate(
            agent, cases, backend, eval_run, run_name=f"prompt-gate-v{prompt.version}",
            tags={"stage": "week4-prompt-gate", "gate_role": label}, quiet=True,
        )  # fmt: skip
        print(
            f"  pass {metrics['pass_rate']:.3f}  urgent recall {metrics['urgent_recall']:.3f}  "
            f"false alarms {metrics['false_alarm_rate']:.3f}  violations "
            f"{metrics['violation_rate']:.3f}  mean {metrics['mean_seconds']:.1f}s  "
            f"tool errors {metrics.get('tool_errors', 0):g}  retries "
            f"{metrics.get('tool_retries', 0):g}"
        )
        results.append(metrics)
    return results


def _promote(cfg: ProjectConfig, args) -> None:
    from databricks.sdk import WorkspaceClient

    from careconnect.agent.tracing import setup_agent_experiment
    from careconnect.evals.agent import default_cases_path, load_cases

    current = alias_version(cfg, PRODUCTION)
    if current is None:
        raise SystemExit("No production version yet: run `register --set-production` first.")
    if str(args.candidate) == current:
        raise SystemExit(f"Version {current} is already production; nothing to do.")
    production = load_system_prompt(cfg, current, strict=True)
    candidate = load_system_prompt(cfg, str(args.candidate), strict=True)
    print(f"production: version {current} (hash {production.hash})")
    print(f"candidate:  version {candidate.version} (hash {candidate.hash})")

    w = WorkspaceClient()
    setup_agent_experiment(cfg, w.current_user.me().user_name)
    mlflow.openai.autolog()
    backend = args.tools or cfg.agent_tool_backend
    cases = load_cases(default_cases_path())
    prod_runs = _evaluate(cfg, production, "production", args.runs, backend, cases)
    cand_runs = _evaluate(cfg, candidate, "candidate", args.runs, backend, cases)

    promote, reasons = decide(prod_runs, cand_runs)
    print("\nGate")
    for line in reasons:
        print(f"  {line}")
    labels = [f"production run {i}" for i in range(1, len(prod_runs) + 1)]
    labels += [f"candidate run {i}" for i in range(1, len(cand_runs) + 1)]
    problems = health_problems(prod_runs + cand_runs, labels)
    if problems:
        print("\nPlatform health")
        for line in problems:
            print(f"  {line}")
        print(
            f"\nINCONCLUSIVE: kept version {current} as production. Tool lookups were failing "
            "or slow, so these scores measure the platform, not the prompt. Run promote again "
            "later (check speed first with one evaluation)."
        )
        return
    if not promote:
        print(f"\nKEPT version {current} as production: the candidate did not pass every check.")
        return
    if args.dry_run:
        print(f"\nWould promote version {candidate.version} (dry run: alias not moved).")
        return
    set_alias(cfg, PREVIOUS, current)
    set_alias(cfg, PRODUCTION, candidate.version)
    print(f"\nPROMOTED version {candidate.version} to production (previous: version {current}).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="The agent prompt in the Prompt Registry")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="production version, and whether prompts.py matches it")
    reg = sub.add_parser("register", help="register the prompt in prompts.py (or --file)")
    reg.add_argument("-m", "--message", default=None)
    reg.add_argument("--file", default=None, help="register this text file instead")
    reg.add_argument(
        "--set-production", action="store_true", help="first version only: make it production"
    )
    pro = sub.add_parser("promote", help="evaluate a candidate and move production if it wins")
    pro.add_argument("--candidate", required=True, help="version number")
    pro.add_argument("--runs", type=int, default=3)
    pro.add_argument("--tools", default=None, help="tool backend (default: config)")
    pro.add_argument("--dry-run", action="store_true")
    sub.add_parser("rollback", help="point production back at the previous version")
    args = parser.parse_args(argv)

    from careconnect.ingest.main import _find_config

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    print(f"prompt: {cfg.agent_prompt}")

    if args.command == "show":
        current = alias_version(cfg, PRODUCTION)
        previous = alias_version(cfg, PREVIOUS)
        for v in _versions(cfg):
            marks = [
                a for a, n in ((PRODUCTION, current), (PREVIOUS, previous)) if n == str(v.version)
            ]
            print(
                f"  version {v.version}  hash {prompt_hash(v.template)}  "
                f"{(v.commit_message or '')[:60]}" + (f"  <- {', '.join(marks)}" if marks else "")
            )
        print(f"production: {'version ' + current if current else 'not set'}")
        loaded = load_system_prompt(cfg)
        same = loaded.source == "registry" and loaded.text == SYSTEM_PROMPT
        print(f"prompts.py (hash {prompt_hash(SYSTEM_PROMPT)}): "
              + ("same as production" if same else "differs from production"))  # fmt: skip
    elif args.command == "register":
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8")
            source = Path(args.file).name
        else:
            text, source = SYSTEM_PROMPT, "src/careconnect/agent/prompts.py"
        message = args.message or f"from {source} at {_git_commit()}"
        current = alias_version(cfg, PRODUCTION)
        if args.set_production and current is not None:
            raise SystemExit(
                f"Production is already version {current}; new versions go through `promote`."
            )
        version, new = register(cfg, text, message, source)
        print(("registered" if new else "already registered as") + f" version {version} "
              f"(hash {prompt_hash(text)})")  # fmt: skip
        if args.set_production:
            set_alias(cfg, PRODUCTION, version)
            print(f"production -> version {version}")
        elif new:
            print(f"next: promote --candidate {version}")
    elif args.command == "promote":
        _promote(cfg, args)
    elif args.command == "rollback":
        current, previous = alias_version(cfg, PRODUCTION), alias_version(cfg, PREVIOUS)
        if previous is None:
            raise SystemExit("No previous version recorded; nothing to roll back to.")
        set_alias(cfg, PRODUCTION, previous)
        set_alias(cfg, PREVIOUS, current)
        print(f"production -> version {previous} (was version {current})")


if __name__ == "__main__":
    main()
