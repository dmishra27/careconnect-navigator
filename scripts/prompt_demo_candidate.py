"""Write a deliberately weaker prompt, to show the promotion gate keeping production.

It is the production prompt without the two rules added for case a13 on 15 October ("Search
first with the person's own words" and "Answer exactly what was asked"); before those rules
the agent failed a13 ("How long does it take to get my records?"). Written to build/, which
is not committed.

  uv run python scripts/prompt_demo_candidate.py
  uv run python -m careconnect.agent.prompt_registry --env dev register \
      --file build/prompt_candidate_demo.txt -m "demo: without the a13 rules"
"""

from pathlib import Path

from careconnect.agent.prompts import SYSTEM_PROMPT

REMOVED = [
    " Search first with the person's own words; rephrase only if the results do not answer "
    "the question.",
    '- Answer exactly what was asked: "how long" needs the time it takes, "how much" the cost, '
    '"how do I" the steps. Add other details only if they help with that.\n',
]

text = SYSTEM_PROMPT
for rule in REMOVED:
    if rule not in text:
        raise SystemExit(f"rule not found in prompts.py (has it changed?): {rule[:60]}...")
    text = text.replace(rule, "")
out = Path(__file__).resolve().parents[1] / "build" / "prompt_candidate_demo.txt"
out.parent.mkdir(exist_ok=True)
out.write_text(text, encoding="utf-8")
print(f"wrote {out} ({len(SYSTEM_PROMPT) - len(text)} characters removed)")
