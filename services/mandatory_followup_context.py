"""
When the pipeline asks for mandatory fields (e.g. weight) and the user replies with only
that data, the *current* message is short (e.g. "68 kg") while intent/RAG/reasoning need
the *original* question from the prior turn.

This module detects that pattern and returns the prior user message to restore as
`PipelineContext.user_message`, while the raw reply stays in
`metadata["supplemental_user_message"]` for parsing weight.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Markers present in assistant prompts from _create_user_data_clarification_response / StageAgentV2
_USER_DATA_ASSISTANT_MARKERS = (
    "To personalize your recommendations",
    "I need the following information",
    "current weight in kg",
)


def parse_weight_kg(message: str) -> Optional[float]:
    """Parse a weight in kg from free text (shared with StageAgentV2 logic)."""
    if not message or not message.strip():
        return None
    msg_lower = message.lower()

    kg_patterns = [
        r"(?:(?:weight|weigh)\s*(?:is|=|:)?\s*)?(\d+(?:\.\d+)?)\s*(kg|kilograms?)\b",
    ]
    for pat in kg_patterns:
        m = re.search(pat, msg_lower)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None

    lb_patterns = [
        r"(?:(?:weight|weigh)\s*(?:is|=|:)?\s*)?(\d+(?:\.\d+)?)\s*(lb|lbs|pounds?)\b",
    ]
    for pat in lb_patterns:
        m = re.search(pat, msg_lower)
        if m:
            try:
                lb_val = float(m.group(1))
                return lb_val * 0.45359237
            except ValueError:
                return None

    if "weigh" in msg_lower:
        m = re.search(r"weigh\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\b", msg_lower)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None

    # Bare number (e.g. "77", "68.5") — plausible weight range 20–400 kg
    bare = msg_lower.strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", bare)
    if m:
        try:
            val = float(m.group(1))
            if 20.0 <= val <= 400.0:
                return val
        except ValueError:
            pass

    return None


def _last_user_content(history: List[Dict[str, Any]]) -> Optional[str]:
    for msg in reversed(history):
        if msg.get("role") == "user":
            text = (msg.get("content") or "").strip()
            return text or None
    return None


def _last_assistant_content(history: List[Dict[str, Any]]) -> Optional[str]:
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            return (msg.get("content") or "") or None
    return None


def _assistant_asked_for_mandatory_fields(assistant_text: str) -> bool:
    if not assistant_text:
        return False
    return any(marker in assistant_text for marker in _USER_DATA_ASSISTANT_MARKERS)


def _looks_like_prior_user_question(text: str) -> bool:
    """Heuristic: prior turn was a real question, not a numeric follow-up."""
    t = (text or "").strip().lower()
    if len(t) < 6:
        return False
    if "?" in t:
        return True
    return any(
        k in t
        for k in (
            "what should",
            "what can",
            "what do",
            "how ",
            "why ",
            "should i",
            "eat",
            "food",
            "diet",
            "nutrition",
            "recipe",
            "exercise",
            "walk",
            "feel",
            "pain",
            "symptom",
        )
    )


def resolve_original_question_if_mandatory_followup(
    current_message: str,
    conversation_history: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[str], Optional[str]]:
    """
    If the user is replying with mandatory-field data (e.g. weight) after our prompt,
    return (original_question_for_pipeline, raw_supplemental_message).

    Otherwise return (None, None) and the caller keeps `current_message` as-is.
    """
    history = conversation_history or []
    if not history:
        return None, None

    weight = parse_weight_kg(current_message)
    if weight is None:
        return None, None

    # Avoid treating long messages as "only weight"
    if len(current_message.strip()) > 500:
        return None, None

    last_user = _last_user_content(history)
    if not last_user or len(last_user) < 3:
        return None, None

    last_asst = _last_assistant_content(history)

    # Strong signal: last assistant turn was our mandatory-fields prompt
    if last_asst and _assistant_asked_for_mandatory_fields(last_asst):
        return last_user, current_message.strip()

    # Weaker fallback (e.g. partial history): assistant asked something about weight/kg
    if last_asst and len(current_message.strip()) < 120 and len(last_user) > 12:
        low = last_asst.lower()
        if "weight" in low or " kg" in low or "kg?" in low:
            return last_user, current_message.strip()

    # Frontend often omits the assistant message: only [user: original Q] then user sends "68 kg"
    if (
        len(current_message.strip()) < 120
        and last_user
        and last_user.strip().lower() != current_message.strip().lower()
        and _looks_like_prior_user_question(last_user)
    ):
        return last_user, current_message.strip()

    return None, None
