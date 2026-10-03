"""
User Data Configuration

Defines field definitions and which fields are mandatory per intent (after Intent Agent).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from config.pipeline_config import IntentCategory

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Nutrition dataset JSON (demo / fallback rows by Patient_ID)
USER_PROFILE_JSON_PATH = BACKEND_ROOT / "data" / "NutritionDataSetxlsx.json"

# Canonical field keys → validation + prompt metadata (used for any intent that lists the key)
FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "weight": {
        "label": "Weight",
        "unit": "kg",
        "prompt": "What is your current weight in kg? (for example: 68 kg)",
        "min_value": 20.0,
        "max_value": 400.0,
    },
    "height_cm": {
        "label": "Height",
        "unit": "cm",
        "prompt": "What is your current height in cm? (for example: 165 cm)",
        "min_value": 50.0,
        "max_value": 250.0,
    },
    "waist_circumference_cm": {
        "label": "Waist circumference",
        "unit": "cm",
        "prompt": "What is your waist circumference in cm? (for example: 82 cm)",
        "min_value": 30.0,
        "max_value": 250.0,
    },
    "hand_grip_strength_kg": {
        "label": "Hand grip strength",
        "unit": "kg",
        "prompt": "What is your hand grip strength in kg? (for example: 22 kg)",
        "min_value": 0.0,
        "max_value": 150.0,
    },
}

# Intent (string value from IntentCategory) → list of mandatory FIELD keys for that intent.
# Intents not listed fall back to DEFAULT_INTENT_MANDATORY_KEYS.
# Empty list = no mandatory user-data gate for that intent.
MANDATORY_FIELD_KEYS_BY_INTENT: Dict[str, List[str]] = {
    # Personalized lifestyle / planning
    "nutrition": ["weight"],
    "exercise": ["weight"],
    # No mandatory profile fields for these (extend as needed)
    "symptoms": [],
    "surgery_procedures": [],
    "drains_wound_care": [],
    "cancer_treatment": [],
    "medication_info": [],
    "side_effects": [],
    "pre_surgery_prehab": [],
    "post_surgery_recovery": [],
    "follow_up_care": [],
    "clothing": [],
    "emotional_support": [],
    "diagnosis_testing": [],
    "admin_logistics": [],
    "safety_red_flags": [],
    "statistics": [],
    "unknown": [],
}

# Used when an intent has no entry in MANDATORY_FIELD_KEYS_BY_INTENT
DEFAULT_INTENT_MANDATORY_KEYS: List[str] = []


def get_mandatory_field_rules_for_intent(
    intent: Optional[Union[IntentCategory, str]],
) -> Dict[str, Dict[str, Any]]:
    """
    Resolve which fields are mandatory for this intent and return their rule dicts.

    Keys match ctx.metadata['user_data'] (e.g. 'weight').
    """
    if intent is None:
        intent_key = IntentCategory.UNKNOWN.value
    elif isinstance(intent, IntentCategory):
        intent_key = intent.value
    else:
        intent_key = str(intent)
    keys = MANDATORY_FIELD_KEYS_BY_INTENT.get(intent_key)
    if keys is None:
        keys = list(DEFAULT_INTENT_MANDATORY_KEYS)

    out: Dict[str, Dict[str, Any]] = {}
    for k in keys:
        if k in FIELD_DEFINITIONS:
            out[k] = FIELD_DEFINITIONS[k]
        else:
            # Misconfiguration: skip unknown keys
            continue
    return out


# Backwards compatibility for imports of MANDATORY_USER_DATA_FIELDS (all defined fields)
MANDATORY_USER_DATA_FIELDS = FIELD_DEFINITIONS
