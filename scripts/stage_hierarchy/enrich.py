#!/usr/bin/env python3
"""
Script to add display_name and search_terms to stage_hierarchy.json
Preserves all existing data while adding new fields.
"""
import json
from pathlib import Path

# Display name mappings (technical name -> user-friendly)
DISPLAY_NAMES = {
    "Pre-diagnosis": "Getting Tests Done",
    "Results Clinic": "Receiving My Diagnosis",
    "palliative": "Comfort & Supportive Care",
    "primary endocrine": "Starting Hormone Therapy",
    "Follow-up Clinic": "My Follow-up Appointment",
    "Continue same endocrine treatment": "Continuing My Hormone Treatment",
    "Change to another medication": "Trying a Different Medication",
    "Further investigation": "More Tests Needed",
    "neoadjuvant chemotherapy": "Chemotherapy Before Surgery",
    "Neo-adjuvant Clinic": "Pre-Surgery Treatment Clinic",
    "Breast surgery": "Having My Surgery",
    "Breast conservation": "Breast-Conserving Surgery",
    "Mastectomy": "Full Breast Removal",
    "SLNB": "Checking Lymph Nodes",
    "Axillary node clearance": "Lymph Node Removal",
    "radiotherapy": "Radiation Treatment",
    "adjuvant chemotherapy": "Chemotherapy After Surgery",
    "Targeted therapy": "Targeted Drug Treatment",
    "radiotherapy to axilla": "Radiation to Armpit Area",
    "No radiotherapy": "No Radiation Needed",
    "breast radiotherapy": "Radiation to Breast",
    "boost": "Extra Radiation Boost",
    "endocrime therapy": "Hormone Therapy",
    "Tamoxifen": "Taking Tamoxifen",
    "AI with bisphosphonates or denosumab": "Taking Hormone Blockers",
    "Ovarian suppression with AI and bisphosphonate or denosumab": "Ovarian Suppression Treatment",
    "Follow-up": "My Regular Check-ups",
    "mammogram yearly": "Yearly Mammogram",
    "5+1": "Extended Follow-up Care",
    "Bone health": "Bone Health Check",
    "Reconstruction": "Breast Reconstruction",
    "Immediate reconstruction": "Reconstruction During Surgery",
    "Delayed reconstruction": "Reconstruction Later",
    "implants": "Implant Reconstruction",
    "Autologous": "Using My Own Tissue",
    "clinical trial": "Joining a Clinical Trial",
}

# Search terms mappings (technical name -> patient-language keywords)
SEARCH_TERMS = {
    "Pre-diagnosis": ["waiting for results", "having tests", "mammogram", "biopsy", "waiting to find out"],
    "Results Clinic": ["got my diagnosis", "found out I have cancer", "just diagnosed", "hearing the news"],
    "palliative": ["incurable", "comfort care", "quality of life", "managing symptoms"],
    "primary endocrine": ["hormone pills", "taking tablets", "hormone blocker"],
    "Breast surgery": ["having surgery", "going for operation", "surgery date", "had my operation", "had surgery", "finished surgery", "surgery done"],
    "Breast conservation": ["lumpectomy", "partial removal", "keeping my breast"],
    "Mastectomy": ["breast removed", "mastectomy", "lost my breast", "took the whole breast"],
    "radiotherapy": ["radiation", "radiotherapy", "zapping", "radio treatment", "getting zapped"],
    "adjuvant chemotherapy": ["chemo after surgery", "post-surgery chemo", "starting chemo"],
    "neoadjuvant chemotherapy": ["chemo before surgery", "shrinking tumor", "pre-surgery chemo"],
    "endocrime therapy": ["hormone therapy", "tamoxifen", "aromatase inhibitor", "hormone pills"],
    "Follow-up": ["check-up", "follow-up appointment", "seeing doctor again", "regular scans"],
    "Reconstruction": ["rebuilding breast", "reconstruction", "new breast"],
    "clinical trial": ["research study", "trial", "experimental treatment"],
}

def add_fields_to_stages(input_path: Path, output_path: Path):
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    for stage_id, stage in data.get("stages", {}).items():
        name = stage.get("name", "")
        
        # Add display_name (use mapping or fallback to title-cased name)
        if name in DISPLAY_NAMES:
            stage["display_name"] = DISPLAY_NAMES[name]
        else:
            # Fallback: title case the name
            stage["display_name"] = name.replace("_", " ").title()
        
        # Add search_terms (use mapping or empty list)
        if name in SEARCH_TERMS:
            stage["search_terms"] = SEARCH_TERMS[name]
        else:
            stage["search_terms"] = []
    
    # Write back with nice formatting
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Updated {len(data.get('stages', {}))} stages with display_name and search_terms")

if __name__ == "__main__":
    input_path = Path(__file__).parent.parent.parent / "data" / "stage_hierarchy.json"
    output_path = input_path  # Overwrite in place
    add_fields_to_stages(input_path, output_path)
    print("Done!")
