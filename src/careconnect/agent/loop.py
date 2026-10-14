"""The agent loop, written out by hand so every step of orchestration is visible.

  1. Send the conversation and the tool schemas to the model.
  2. If the model asks for tools, run each one and add the results to the conversation.
  3. Repeat until the model answers in text, or MAX_STEPS is reached.

Two safety rules run in code around the loop (see guardrails.py): urgent symptoms get a
fixed 999 / NHS 24 message without calling the model, and an answer given without any
successful tool call is replaced by a standard out-of-scope message.

Every model call and tool call is traced in MLflow (one trace per question).
"""

from dataclasses import dataclass, field

import mlflow

from careconnect.agent import guardrails
from careconnect.agent.prompts import SYSTEM_PROMPT
from careconnect.agent.tools import Toolbox

MAX_STEPS = 6
FALLBACK = (
    "Sorry, I could not complete that. Please contact the Patient Services Contact Centre "
    "on 01632 960 100."
)


@dataclass
class ToolCall:
    name: str
    arguments: str
    result: str


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    steps: int = 0
    stopped: str = "answer"  # answer | max_steps | urgent | no_grounding
    guard: str | None = None  # which guardrail acted, if any


class Agent:
    def __init__(self, client, model: str, toolbox: Toolbox, max_steps: int = MAX_STEPS):
        self.client, self.model, self.toolbox, self.max_steps = client, model, toolbox, max_steps

    @mlflow.trace(name="careconnect_agent", span_type="AGENT")
    def run(self, question: str, history: list[dict] | None = None) -> AgentResult:
        urgent = guardrails.urgent_category(question)
        if urgent:  # never wait for the model when someone may need 999
            return AgentResult(
                answer=guardrails.URGENT_MESSAGES[urgent], stopped="urgent", guard=urgent
            )
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or [])]
        messages.append({"role": "user", "content": question})
        result = AgentResult(answer="")
        for step in range(1, self.max_steps + 1):
            result.steps = step
            reply = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.toolbox.schemas(),
                temperature=0,
                max_tokens=700,
            )
            msg = reply.choices[0].message
            if not msg.tool_calls:
                result.answer = (msg.content or "").strip() or FALLBACK
                if not any(guardrails.is_successful(c.result) for c in result.tool_calls):
                    # answered from the model's memory, not our documents or data
                    result.answer = guardrails.OUT_OF_SCOPE
                    result.stopped, result.guard = "no_grounding", "no_grounding"
                return result
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.function.name,
                                "arguments": c.function.arguments,
                            },
                        }
                        for c in msg.tool_calls
                    ],
                }
            )
            for c in msg.tool_calls:
                output = self.toolbox.run(c.function.name, c.function.arguments)
                result.tool_calls.append(ToolCall(c.function.name, c.function.arguments, output))
                messages.append({"role": "tool", "tool_call_id": c.id, "content": output})
        result.answer, result.stopped = FALLBACK, "max_steps"
        return result
