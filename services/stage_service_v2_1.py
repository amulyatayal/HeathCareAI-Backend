"""
V2.1 Journey Engine Service Extensions
Additional methods for PatientStageService (safety triggers & regression detection).

Import and call these methods with a PatientStageService instance.
"""

from typing import Dict, Any, Optional


def check_for_safety_triggers(service, user_message: str, country_code: str = "GB") -> Dict[str, Any]:
    """
    Check user message for safety triggers with geo-aware emergency numbers.
    
    Args:
        service: PatientStageService instance
        user_message: User's input message
        country_code: Country code (GB/US)
    
    Returns:
        {
            "has_triggers": bool,
            "matched_keywords": List[str],
            "emergency_number": str,
            "urgent_number": str
        }
    """
    service._ensure_loaded()
    
    # Collect safety keywords from all stages
    safety_keywords = set()
    for stage in service._stages.values():
        safety_keywords.update(stage.safety_triggers)
    
    # Check message
    message_lower = user_message.lower()
    matched = [k for k in safety_keywords if k in message_lower]
    
    # Geo-aware emergency numbers
    emergency_numbers = {
        "GB": {"emergency": "999", "urgent": "111"},
        "US": {"emergency": "911", "urgent": "811"},
    }
    numbers = emergency_numbers.get(country_code, {"emergency": "911", "urgent": "811"})
    
    return {
        "has_triggers": len(matched) > 0,
        "matched_keywords": matched,
        "emergency_number": numbers["emergency"],
        "urgent_number": numbers.get("urgent"),
    }


def detect_regression(service, from_stage_id: Optional[str], to_stage_id: str) -> Dict[str, Any]:
    """
    Detect if stage transition represents regression/recurrence.
    
    Logic:
        - Type 1 (Recurrence): Survivorship (Group 5) → Treatment (6, 7, 8, 9)
        - Type 2 (New Primary): Post-treatment (7-10) → Early stages (0-1)
    
    Args:
        service: PatientStageService instance
        from_stage_id: Previous stage ID (e.g., "5.1")
        to_stage_id: New stage ID (e.g., "8.1")
    
    Returns:
        {
            "is_regression": bool,
            "regression_type": "recurrence" | "new_primary" | None,
            "message": str (empathy message)
        }
    """
    if not from_stage_id:
        return {"is_regression": False, "regression_type": None, "message": ""}
    
    # Extract stage groups
    try:
        from_group = int(from_stage_id.split('.')[0])
        to_group = int(to_stage_id.split('.')[0])
    except (ValueError, IndexError):
        return {"is_regression": False, "regression_type": None, "message": ""}
    
    # Type 1: Recurrence (Survivorship → Treatment)
    if from_group == 5 and to_group in [6, 7, 8, 9]:
        return {
            "is_regression": True,
            "regression_type": "recurrence",
            "message": "I'm sorry to hear about your recurrence. This must be incredibly difficult.",
        }
    
    # Type 2: New Primary (Post-treatment → Early stages)
    if from_group in [7, 8, 9, 10] and to_group in [0, 1]:
        return {
            "is_regression": True,
            "regression_type": "new_primary",
            "message": "I see this is a new diagnosis. I'm here to support you.",
        }
    
    return {"is_regression": False, "regression_type": None, "message": ""}
