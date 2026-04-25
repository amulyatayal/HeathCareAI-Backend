"""Unit tests for mandatory follow-up context restoration."""

from services.mandatory_followup_context import resolve_original_question_if_mandatory_followup


def test_no_change_after_weight_confirmation_restores_original_question():
    history = [
        {"role": "user", "content": "What should I eat during chemo?"},
        {
            "role": "assistant",
            "content": (
                "I have your current weight as 65.0 kg. "
                "Has this changed? If yes, please share your updated weight in kg."
            ),
        },
    ]
    orig, supplemental = resolve_original_question_if_mandatory_followup(
        "no change",
        history,
    )
    assert orig == "What should I eat during chemo?"
    assert supplemental == "no change"


def test_numeric_weight_reply_still_restores():
    history = [
        {"role": "user", "content": "What should I eat during chemo?"},
        {
            "role": "assistant",
            "content": (
                "I have your current weight as 65.0 kg. "
                "Has this changed? If yes, please share your updated weight in kg."
            ),
        },
    ]
    orig, supplemental = resolve_original_question_if_mandatory_followup(
        "70 kg",
        history,
    )
    assert orig == "What should I eat during chemo?"
    assert supplemental == "70 kg"


def test_chained_height_reply_restores_original_question_not_weight_reply():
    history = [
        {"role": "user", "content": "What should I eat during chemo?"},
        {
            "role": "assistant",
            "content": (
                "I have your current weight as 65.0 kg. "
                "Has this changed? If yes, please share your updated weight in kg."
            ),
        },
        {"role": "user", "content": "70 kg"},
        {
            "role": "assistant",
            "content": (
                "I have your current height as 165.0 cm. "
                "Has this changed? If yes, please share your updated height in cm."
            ),
        },
    ]
    orig, supplemental = resolve_original_question_if_mandatory_followup(
        "166 cm",
        history,
    )
    assert orig == "What should I eat during chemo?"
    assert supplemental == "166 cm"


def test_chained_waist_reply_restores_original_question_after_no_change_height():
    history = [
        {"role": "user", "content": "What should I eat during chemo?"},
        {
            "role": "assistant",
            "content": (
                "I have your current weight as 65.0 kg. "
                "Has this changed? If yes, please share your updated weight in kg."
            ),
        },
        {"role": "user", "content": "70 kg"},
        {
            "role": "assistant",
            "content": (
                "I have your current height as 165.0 cm. "
                "Has this changed? If yes, please share your updated height in cm."
            ),
        },
        {"role": "user", "content": "no change"},
        {
            "role": "assistant",
            "content": (
                "I have your waist circumference as 82.0 cm. "
                "Has this changed? If yes, please share your updated waist circumference in cm."
            ),
        },
    ]
    orig, supplemental = resolve_original_question_if_mandatory_followup(
        "84 cm",
        history,
    )
    assert orig == "What should I eat during chemo?"
    assert supplemental == "84 cm"
