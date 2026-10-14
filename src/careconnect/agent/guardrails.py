"""Safety rules enforced in code, not left to the model.

1. Urgent symptoms: checked BEFORE the model is called. If a question describes a possible
   emergency, the agent answers with a fixed safety message and never calls the model, so
   no prompt wording, model change or clever phrasing can delay "call 999".
2. Grounding: checked AFTER the model answers. An answer given without any successful tool
   call came from the model's memory, not our documents, so it is replaced with a standard
   "I can only help with..." message.

The urgent patterns follow the leaflet "When to call NHS 24 or 999" (fvhb-20). They are
deliberately broad: a false alarm costs a patient one extra sentence, a miss could cost far
more. Phrases are specific enough that service questions ("Where is the stroke clinic?")
do not trigger them; the evaluation set checks both directions.
"""

import json
import re

EMERGENCY = "emergency"
MENTAL_HEALTH = "mental_health"

_PATTERNS: dict[str, list[str]] = {
    EMERGENCY: [
        r"chest (pain|pains|tightness|pressure)",
        r"pain in (my|his|her|their) chest",
        r"(can'?t|cannot|can not|struggling to|difficulty|trouble|hard to) (breathe|breathing)",
        r"short(ness)? of breath",
        r"\bchoking\b",
        r"face (is |has |was )?(drooping|droopy|dropped|fallen)",
        r"slurr(ed|ing) (speech|words|his words|her words)",
        r"(speech|talking) (is |has |was )?slurred",
        r"(having|had|signs of|symptoms of|think .{0,20}) a stroke",
        r"arm (weakness|is weak|went weak|gone numb)",
        r"(heavy|severe|won'?t stop|will not stop|can'?t stop) bleeding",
        r"bleeding (heavily|badly|won'?t stop|will not stop)",
        r"(unconscious|passed out|collapsed|not breathing|unresponsive)",
        r"(seizure|fit) (that |which )?(won'?t|will not|doesn'?t|does not) stop",
        r"(serious|bad|severe) head injury",
        r"(throat|tongue|lips) (is |are )?(swelling|swollen)",
        r"anaphyla",
        r"\boverdose",
    ],
    MENTAL_HEALTH: [
        r"(kill|harm|hurt) (myself|himself|herself|themselves)",
        r"suicid",
        r"end (my|his|her) life",
        r"(don'?t|do not) want to (live|be alive|be here)",
        r"self[- ]harm",
    ],
}
_COMPILED = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in _PATTERNS.items()}

LEAFLET = "(When to call NHS 24 or 999)"

URGENT_MESSAGES = {
    EMERGENCY: (
        "This could be a medical emergency. Call 999 now. If it is urgent but not "
        "life-threatening, call NHS 24 on 111, free, 24 hours a day. "
        f"{LEAFLET}\n\nI cannot give medical advice. When you are safe, I can help with "
        "appointments, clinics and other hospital services."
    ),
    MENTAL_HEALTH: (
        "I'm sorry you are going through this. If you or someone else is in immediate "
        "danger, call 999 now. You can also call NHS 24 on 111 and choose the mental health "
        "option, Samaritans on 116 123 (24 hours a day), or Breathing Space on 0800 83 85 87. "
        f"All are free and confidential. {LEAFLET}"
    ),
}

OUT_OF_SCOPE = (
    "I could not find an answer to that in our leaflets, NHS Scotland guidance, clinic list or "
    "published waiting-times figures, so I would rather not guess. The Patient Services "
    "Contact Centre on 01632 960 100 can help with questions about our services. For medical "
    "advice, speak to your GP, a pharmacist or NHS 24 on 111."
)


def urgent_category(question: str) -> str | None:
    """The kind of urgent situation the question describes, or None."""
    for category in (MENTAL_HEALTH, EMERGENCY):
        if any(p.search(question) for p in _COMPILED[category]):
            return category
    return None


def is_successful(tool_output: str) -> bool:
    """A tool call that returned something other than an error or nothing at all."""
    try:
        data = json.loads(tool_output)
    except (json.JSONDecodeError, TypeError):
        return bool(tool_output and tool_output.strip())
    if isinstance(data, dict) and "error" in data:
        return False
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return bool(data["rows"])
    return bool(data)
