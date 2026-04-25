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
    "current height in cm",
    "waist circumference in cm",
    # Confirmation prompts (StageAgentV2) — substring "current weight in kg" does not appear there
    "Has this changed?",
    "I have your current weight",
    "I have your current height",
    "I have your waist circumference",
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


def parse_height_cm(message: str) -> Optional[float]:
    """Parse height in cm from free text (supports cm, m, feet/inches)."""
    if not message or not message.strip():
        return None
    msg_lower = message.lower()

    cm_patterns = [
        r"(?:(?:height)\s*(?:is|=|:)?\s*)?(\d+(?:\.\d+)?)\s*(cm|centimeters?)\b",
    ]
    for pat in cm_patterns:
        m = re.search(pat, msg_lower)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None

    m_patterns = [
        r"(?:(?:height)\s*(?:is|=|:)?\s*)?(\d+(?:\.\d+)?)\s*(m|meters?)\b",
    ]
    for pat in m_patterns:
        m = re.search(pat, msg_lower)
        if m:
            try:
                return float(m.group(1)) * 100.0
            except ValueError:
                return None

    feet_inches = re.search(
        r"(?:(?:height)\s*(?:is|=|:)?\s*)?(\d+)\s*(?:ft|feet|')\s*(\d+)?\s*(?:in|inch|inches|\")?\b",
        msg_lower,
    )
    if feet_inches:
        try:
            feet = int(feet_inches.group(1))
            inches = int(feet_inches.group(2)) if feet_inches.group(2) else 0
            total_inches = feet * 12 + inches
            return total_inches * 2.54
        except ValueError:
            return None

    if "height" in msg_lower:
        m = re.search(r"height\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\b", msg_lower)
        if m:
            try:
                val = float(m.group(1))
                if 50.0 <= val <= 250.0:
                    return val
            except ValueError:
                return None

    return None


def parse_waist_circumference_cm(message: str) -> Optional[float]:
    """Parse waist circumference in cm from free text."""
    if not message or not message.strip():
        return None
    msg_lower = message.lower()

    patterns = [
        r"(?:(?:waist|waist circumference)\s*(?:is|=|:)?\s*)?(\d+(?:\.\d+)?)\s*(cm|centimeters?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, msg_lower)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None

    if "waist" in msg_lower:
        m = re.search(r"waist(?: circumference)?\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\b", msg_lower)
        if m:
            try:
                val = float(m.group(1))
                if 30.0 <= val <= 250.0:
                    return val
            except ValueError:
                return None

    return None


def parse_hand_grip_strength_kg(message: str) -> Optional[float]:
    """Parse hand grip strength in kg from free text."""
    if not message or not message.strip():
        return None
    msg_lower = message.lower()

    patterns = [
        r"(?:(?:hand\s*grip|grip\s*strength|grip)\s*(?:is|=|:)?\s*)?(\d+(?:\.\d+)?)\s*(kg|kilograms?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, msg_lower)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None

    if "grip" in msg_lower:
        m = re.search(r"(?:hand\s*grip|grip(?:\s*strength)?)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\b", msg_lower)
        if m:
            try:
                val = float(m.group(1))
                if 0.0 <= val <= 150.0:
                    return val
            except ValueError:
                return None

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


def _last_user_before_last_assistant(history: List[Dict[str, Any]]) -> Optional[str]:
    """
    Return the most recent user message that occurred *before* the most recent
    assistant turn. This preserves the original question across chained
    mandatory prompts (weight -> height -> waist).
    """
    last_assistant_idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("role") == "assistant":
            last_assistant_idx = i
            break
    if last_assistant_idx is None:
        return _last_user_content(history)

    for i in range(last_assistant_idx - 1, -1, -1):
        if history[i].get("role") == "user":
            text = (history[i].get("content") or "").strip()
            return text or None
    return None


def _assistant_asked_for_mandatory_fields(assistant_text: str) -> bool:
    if not assistant_text:
        return False
    return any(marker in assistant_text for marker in _USER_DATA_ASSISTANT_MARKERS)


def _is_no_change_measurement_reply(message: str) -> bool:
    """User confirms an existing measurement is still correct (no new number)."""
    text = (message or "").strip().lower()
    if not text:
        return False
    patterns = [
        r"^(no|nope|nah)$",
        r"^(no change|unchanged|same)$",
        r"^(it('| i)?s the same|still the same)$",
        r"^(no changes)$",
        r"^same as before$",
        r"^not changed$",
        r"^correct$",
        r"^yes,?\s*(that'?s|it is)\s*(right|correct)$",
    ]
    return any(re.match(p, text) for p in patterns)


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
    height = parse_height_cm(current_message)
    waist = parse_waist_circumference_cm(current_message)
    grip = parse_hand_grip_strength_kg(current_message)
    has_parsed_measurement = any(
        v is not None for v in (weight, height, waist, grip)
    )
    if not has_parsed_measurement and not _is_no_change_measurement_reply(current_message):
        return None, None

    # Avoid treating long messages as "only weight"
    if len(current_message.strip()) > 500:
        return None, None

    # Prefer the latest user question before the latest assistant prompt.
    # This avoids restoring to previous measurement replies in chained flows.
    last_user = _last_user_before_last_assistant(history)
    if not last_user:
        last_user = _last_user_content(history)
    if not last_user or len(last_user) < 3:
        return None, None

    last_asst = _last_assistant_content(history)

    # Strong signal: last assistant turn was our mandatory-fields prompt
    if last_asst and _assistant_asked_for_mandatory_fields(last_asst):
        return last_user, current_message.strip()

    # Weaker fallback (e.g. partial history): assistant asked something about weight/height
    if last_asst and len(current_message.strip()) < 120 and len(last_user) > 12:
        low = last_asst.lower()
        if (
            "weight" in low
            or "height" in low
            or "waist" in low
            or "grip" in low
            or " kg" in low
            or " cm" in low
            or "kg?" in low
            or "cm?" in low
        ):
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
