"""
Nutrition Knowledge Base Enums and Constants

Defines canonical values for recipes and dietary advice used in the nutrition KB.
"""

from enum import Enum
from typing import List, Dict


class MealType(str, Enum):
    """Types of meals for recipes."""
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    SMOOTHIE = "smoothie"
    SOUP = "soup"
    DESSERT = "dessert"


class CuisineType(str, Enum):
    """Cuisine categories for recipes."""
    INDIAN = "indian"
    MEDITERRANEAN = "mediterranean"
    MEXICAN = "mexican"
    ASIAN = "asian"
    AMERICAN = "american"
    MIDDLE_EASTERN = "middle_eastern"
    AFRICAN = "african"
    EUROPEAN = "european"
    LATIN_AMERICAN = "latin_american"
    JAPANESE = "japanese"
    CHINESE = "chinese"
    THAI = "thai"
    KOREAN = "korean"


class DietaryTag(str, Enum):
    """Dietary restriction and preference tags."""
    # Lifestyle
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"
    
    # Allergen-free
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    SOY_FREE = "soy_free"
    EGG_FREE = "egg_free"
    SHELLFISH_FREE = "shellfish_free"
    
    # Religious
    HALAL = "halal"
    KOSHER = "kosher"
    
    # Nutritional focus
    LOW_SALT = "low_salt"
    LOW_SUGAR = "low_sugar"
    LOW_FAT = "low_fat"
    HIGH_PROTEIN = "high_protein"
    HIGH_FIBER = "high_fiber"
    HIGH_CALORIE = "high_calorie"
    LOW_FODMAP = "low_fodmap"
    ANTI_INFLAMMATORY = "anti_inflammatory"


class TextureClass(str, Enum):
    """Food texture classifications for patients with swallowing difficulties."""
    REGULAR = "regular"
    SOFT = "soft"
    MINCED = "minced"
    PUREED = "pureed"
    LIQUID = "liquid"


class SymptomTag(str, Enum):
    """Treatment-related symptoms that recipes can help manage."""
    NAUSEA = "nausea"
    FATIGUE = "fatigue"
    MOUTH_SORES = "mouth_sores"
    DRY_MOUTH = "dry_mouth"
    CONSTIPATION = "constipation"
    DIARRHEA = "diarrhea"
    TASTE_CHANGES = "taste_changes"
    DIFFICULTY_SWALLOWING = "difficulty_swallowing"
    APPETITE_LOSS = "appetite_loss"
    WEIGHT_LOSS = "weight_loss"
    WEIGHT_GAIN = "weight_gain"
    BLOATING = "bloating"
    HEARTBURN = "heartburn"
    NEUTROPENIA = "neutropenia"  # Low white blood cell count - food safety


class TreatmentStage(str, Enum):
    """
    Treatment stages from BreastCancerStagesProcessed.csv
    Maps stage IDs to patient-friendly names.
    """
    PRE_DIAGNOSIS = "0"
    NEWLY_DIAGNOSED = "1"
    SURGERY = "2"
    NEOADJUVANT_CHEMO = "3"
    NEOADJUVANT_ENDOCRINE = "4"
    SURVIVORSHIP = "5"
    FURTHER_SURGERY = "6"
    RADIOTHERAPY = "7"
    ADJUVANT_CHEMO = "8"
    ADJUVANT_ENDOCRINE = "9"


# Stage metadata for LLM prompts
STAGE_CONTEXT: Dict[str, Dict] = {
    "0": {
        "name": "Pre-diagnosis",
        "display_name": "Waiting for Test Results",
        "nutrition_focus": "General healthy eating, stress management",
        "common_symptoms": ["anxiety", "appetite_loss"]
    },
    "1": {
        "name": "Newly Diagnosed",
        "display_name": "Just Diagnosed",
        "nutrition_focus": "Building strength for treatment, immune support",
        "common_symptoms": ["appetite_loss", "anxiety"]
    },
    "2": {
        "name": "Surgery",
        "display_name": "Having Surgery",
        "nutrition_focus": "Pre-surgery preparation, post-surgery recovery, wound healing",
        "common_symptoms": ["fatigue", "constipation", "appetite_loss"]
    },
    "3": {
        "name": "Neoadjuvant Chemotherapy",
        "display_name": "Chemotherapy Before Surgery",
        "nutrition_focus": "Managing chemo side effects, maintaining weight, hydration",
        "common_symptoms": ["nausea", "fatigue", "taste_changes", "mouth_sores", "constipation", "diarrhea", "neutropenia"]
    },
    "4": {
        "name": "Neoadjuvant Endocrine",
        "display_name": "Hormone Therapy Before Surgery",
        "nutrition_focus": "Managing hormone therapy side effects, bone health",
        "common_symptoms": ["weight_gain", "fatigue", "bloating"]
    },
    "5": {
        "name": "Survivorship",
        "display_name": "Finished Active Treatment",
        "nutrition_focus": "Long-term health, cancer prevention, healthy weight",
        "common_symptoms": ["fatigue", "weight_management"]
    },
    "6": {
        "name": "Further Surgery",
        "display_name": "Additional Surgery",
        "nutrition_focus": "Recovery, wound healing, rebuilding strength",
        "common_symptoms": ["fatigue", "constipation", "appetite_loss"]
    },
    "7": {
        "name": "Radiotherapy",
        "display_name": "Having Radiotherapy",
        "nutrition_focus": "Skin health, energy maintenance, hydration",
        "common_symptoms": ["fatigue", "skin_sensitivity", "dry_mouth"]
    },
    "8": {
        "name": "Adjuvant Chemotherapy",
        "display_name": "Chemotherapy After Surgery",
        "nutrition_focus": "Managing chemo side effects, maintaining weight, immune support",
        "common_symptoms": ["nausea", "fatigue", "taste_changes", "mouth_sores", "constipation", "diarrhea", "neutropenia"]
    },
    "9": {
        "name": "Adjuvant Endocrine Therapy",
        "display_name": "Hormone Therapy After Surgery",
        "nutrition_focus": "Bone health, weight management, heart health",
        "common_symptoms": ["weight_gain", "fatigue", "bone_health"]
    }
}


# Nutrition data structure template
NUTRITION_FIELDS = [
    "calories_per_serving",
    "protein_g",
    "fiber_g",
    "fat_g",
    "saturated_fat_g",
    "carbs_g",
    "sugar_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "vitamin_c_mg",
    "vitamin_d_mcg"
]


def get_all_dietary_tags() -> List[str]:
    """Return all dietary tag values as strings."""
    return [tag.value for tag in DietaryTag]


def get_all_cuisine_types() -> List[str]:
    """Return all cuisine type values as strings."""
    return [cuisine.value for cuisine in CuisineType]


def get_all_meal_types() -> List[str]:
    """Return all meal type values as strings."""
    return [meal.value for meal in MealType]


def get_all_symptom_tags() -> List[str]:
    """Return all symptom tag values as strings."""
    return [symptom.value for symptom in SymptomTag]


def get_stage_info(stage_id: str) -> Dict:
    """Get stage metadata by ID."""
    return STAGE_CONTEXT.get(stage_id, {})
