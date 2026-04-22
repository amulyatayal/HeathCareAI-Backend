"""
Build hybrid search query text from pipeline context.

Stage agent merges DB + JSON + message into ctx.metadata['user_data'].
RetrievalAgent uses this so embeddings match the user's question + profile facts.
"""

from __future__ import annotations

from typing import Any, Dict, List

from models.schemas import PipelineContext


def build_retrieval_query(context: PipelineContext) -> str:
    """
    Primary line: user's question (possibly restored after mandatory-field follow-up).
    Appends compact personalization lines from user_data when present.
    """
    base = (context.user_message or "").strip()
    ud: Dict[str, Any] = (context.metadata or {}).get("user_data") or {}

    extras: List[str] = []

    if ud.get("weight") is not None:
        try:
            extras.append(f"Patient weight: {float(ud['weight']):.1f} kg")
        except (TypeError, ValueError):
            extras.append(f"Patient weight: {ud['weight']} kg")
    if ud.get("height_cm") is not None:
        extras.append(f"Patient height: {ud['height_cm']} cm")
    if ud.get("bmi") is not None:
        extras.append(f"Patient BMI: {ud['bmi']}")
    if ud.get("waist_circumference_cm") is not None:
        extras.append(f"Waist circumference: {ud['waist_circumference_cm']} cm")
    if ud.get("hand_grip_strength_kg") is not None:
        extras.append(f"Hand grip strength: {ud['hand_grip_strength_kg']} kg")

    if not extras:
        return base

    return base + "\n\n" + "\n".join(extras) if base else "\n".join(extras)
