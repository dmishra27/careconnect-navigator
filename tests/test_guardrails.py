import pytest

from careconnect.agent.guardrails import (
    EMERGENCY,
    MENTAL_HEALTH,
    URGENT_MESSAGES,
    is_successful,
    urgent_category,
)


@pytest.mark.parametrize(
    "question",
    [
        "I have crushing chest pain going down my left arm",
        "My wife can't breathe properly",
        "Dad's face is drooping and his speech is slurred",
        "I think my mum is having a stroke",
        "My son is choking",
        "The bleeding won't stop",
        "He collapsed and is unresponsive",
        "Her throat is swelling after a bee sting",
    ],
)
def test_emergencies_are_caught(question):
    assert urgent_category(question) == EMERGENCY


@pytest.mark.parametrize(
    "question",
    [
        "I want to kill myself",
        "I don't want to live any more",
        "thoughts of self-harm",
        "I keep thinking about ending my life",
        "He talked about taking his own life",
    ],
)
def test_mental_health_crises_are_caught(question):
    assert urgent_category(question) == MENTAL_HEALTH


@pytest.mark.parametrize(
    "question",
    [
        "Where is the stroke rehabilitation clinic?",
        "How do I get the results of my chest X-ray?",
        "Can I change my hospital appointment more than once?",
        "How long is the wait for cardiology in NHS Lothian?",
        "Is there a breathing space for carers in the waiting room?",
    ],
)
def test_service_questions_with_similar_words_are_not_caught(question):
    assert urgent_category(question) is None


def test_urgent_messages_give_the_right_numbers():
    assert "999" in URGENT_MESSAGES[EMERGENCY] and "111" in URGENT_MESSAGES[EMERGENCY]
    assert "116 123" in URGENT_MESSAGES[MENTAL_HEALTH]


@pytest.mark.parametrize(
    ("output", "ok"),
    [
        ('{"error": "KeyError"}', False),
        ('{"source": "PHS", "rows": []}', False),
        ("[]", False),
        ('[{"name": "Larbank Health Centre"}]', True),
        ('{"columns": ["name"], "rows": [["Larbank"]]}', True),
        ("plain text from an MCP tool", True),
    ],
)
def test_successful_tool_outputs(output, ok):
    assert is_successful(output) is ok
