#!/usr/bin/env python3
"""
Seed pathway resources for development.

Inserts 10 educational resources (real UK cancer charity links)
covering the major treatment pathway stages, assigned to the
dev admin user CLN-DEV001.

Run with:  python scripts/db/seed_pathway_resources.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.pathway_resource_service import get_pathway_resource_service

CLINICIAN_NAME = "Dev Admin"
CLINICIAN_ID = "CLN-DEV001"

RESOURCES = [
    {
        "pathway_stage_ids": ["0"],
        "description": "What to expect from breast cancer screening and tests",
        "intents": ["diagnosis_testing"],
        "resources": [{
            "title": "Your breast clinic appointment - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/visiting-breast-clinic",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["1", "1.3"],
        "description": "Understanding your breast cancer diagnosis",
        "intents": ["diagnosis_testing", "emotional_support"],
        "resources": [{
            "title": "Being diagnosed with breast cancer - Macmillan",
            "url": "https://www.macmillan.org.uk/cancer-information-and-support/breast-cancer/diagnosis",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["2"],
        "description": "Overview of breast cancer surgery types and what to expect",
        "intents": ["surgery_procedures", "pre_surgery_prehab"],
        "resources": [{
            "title": "Surgery for breast cancer - NHS",
            "url": "https://www.nhs.uk/conditions/breast-cancer/treatment/surgery/",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["2.1.1", "2.1.1.1"],
        "description": "Information about lumpectomy (breast conserving surgery)",
        "intents": ["surgery_procedures"],
        "resources": [{
            "title": "Lumpectomy (wide local excision) - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/going-through-treatment/surgery/lumpectomy",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["2.1.2", "2.1.2.1", "2.1.2.2"],
        "description": "Information about mastectomy and reconstruction options",
        "intents": ["surgery_procedures"],
        "resources": [{
            "title": "Mastectomy - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/going-through-treatment/surgery/mastectomy",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["2", "6"],
        "description": "Recovering after breast cancer surgery - exercises, wound care, drains",
        "intents": ["post_surgery_recovery", "drains_wound_care"],
        "resources": [{
            "title": "Recovery after breast cancer surgery - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/going-through-treatment/surgery/recovery-after-surgery",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["3", "3.1", "8"],
        "description": "Understanding chemotherapy for breast cancer - what to expect, side effects",
        "intents": ["cancer_treatment", "side_effects"],
        "resources": [{
            "title": "Chemotherapy for breast cancer - Cancer Research UK",
            "url": "https://www.cancerresearchuk.org/about-cancer/breast-cancer/treatment/chemotherapy",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["7"],
        "description": "What to expect from radiotherapy treatment",
        "intents": ["cancer_treatment", "side_effects"],
        "resources": [{
            "title": "Radiotherapy for breast cancer - Macmillan",
            "url": "https://www.macmillan.org.uk/cancer-information-and-support/breast-cancer/radiotherapy",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["1.2", "9", "9.1", "9.2"],
        "description": "Understanding hormone therapy (endocrine treatment) for breast cancer",
        "intents": ["cancer_treatment", "medication_info", "side_effects"],
        "resources": [{
            "title": "Hormone therapy for breast cancer - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/going-through-treatment/hormone-therapy",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["5", "5.1", "5.2"],
        "description": "Life after breast cancer treatment - follow-up care and wellbeing",
        "intents": ["follow_up_care", "emotional_support", "exercise", "nutrition"],
        "resources": [{
            "title": "Life after breast cancer treatment - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/living-beyond-breast-cancer",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["1.1"],
        "description": "Support and information for secondary (metastatic) breast cancer",
        "intents": ["cancer_treatment", "emotional_support"],
        "resources": [{
            "title": "Secondary breast cancer - Breast Cancer Now",
            "url": "https://breastcancernow.org/information-support/facing-breast-cancer/secondary-metastatic-breast-cancer",
            "type": "link",
        }],
    },
    {
        "pathway_stage_ids": ["3", "8", "7", "5"],
        "description": "Eating well during and after cancer treatment",
        "intents": ["nutrition"],
        "resources": [{
            "title": "Eating well during cancer treatment - Macmillan",
            "url": "https://www.macmillan.org.uk/cancer-information-and-support/impacts-of-cancer/eating-problems",
            "type": "link",
        }],
    },
]


def main():
    print("=" * 60)
    print("  Seeding Pathway Resources")
    print(f"  Clinician: {CLINICIAN_NAME} ({CLINICIAN_ID})")
    print(f"  Resources to insert: {len(RESOURCES)}")
    print("=" * 60)
    print()

    service = get_pathway_resource_service()
    created = 0

    for i, res in enumerate(RESOURCES, 1):
        data = {
            "clinician_name": CLINICIAN_NAME,
            "clinician_id": CLINICIAN_ID,
            **res,
        }
        try:
            result = service.create_resource(data)
            stages = ", ".join(res["pathway_stage_ids"])
            print(f"  [{i}/{len(RESOURCES)}] Created: {res['resources'][0]['title'][:60]}...")
            print(f"           Stages: {stages}")
            created += 1
        except Exception as e:
            print(f"  [{i}/{len(RESOURCES)}] FAILED: {e}")

    print()
    print("=" * 60)
    print(f"  Done! {created}/{len(RESOURCES)} resources seeded.")
    print("=" * 60)


if __name__ == "__main__":
    main()
