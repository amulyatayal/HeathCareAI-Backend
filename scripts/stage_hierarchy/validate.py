
import json
import os
import sys

# Define root of repo
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(BASE_DIR, "data", "stage_hierarchy.json")

def validate_hierarchy():
    print(f"Loading hierarchy from {DATA_PATH}...")
    
    try:
        with open(DATA_PATH, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("ERROR: stage_hierarchy.json not found!")
        sys.exit(1)
        
    stages = data.get("stages", {})
    root_ids = data.get("root_stage_ids", [])
    
    print(f"Loaded {len(stages)} stages.")
    
    errors = []
    warnings = []
    
    # 1. Check Root IDs
    for rid in root_ids:
        if rid not in stages:
            errors.append(f"Root ID '{rid}' does not exist in stages dict.")
            
    # 2. Check each stage
    for stage_id, stage in stages.items():
        # A. Next/Prev Validation
        for child_id in stage.get("child_stage_ids", []):
            if child_id not in stages:
                errors.append(f"Stage '{stage_id}' references non-existent child '{child_id}'")
            else:
                child = stages[child_id]
                if stage_id != child.get("parent_stage_id"):
                    # This is subjective, sometimes parent is null if flexible, but usually stricter
                    warnings.append(f"Child '{child_id}' has parent '{child.get('parent_stage_id')}' but is listed as child of '{stage_id}'")

        # B. Flow Validation (Before/After)
        for prev_id in stage.get("before_stages", []):
            if prev_id != "multiple" and prev_id not in stages:
                 # 'multiple' and 'prediagnosis' are sometimes used as placeholders
                 if prev_id not in ["multiple", "prediagnosis", "unknown"]:
                    errors.append(f"Stage '{stage_id}' has invalid before_stage '{prev_id}'")

        for next_id in stage.get("after_stages", []):
            if next_id != "multiple" and next_id not in stages:
                 if next_id not in ["multiple", "post surgery MDM", "unknown"]:
                     errors.append(f"Stage '{stage_id}' has invalid after_stage '{next_id}'")
            
        # C. Dead Ends (Leaf nodes without after_stages)
        # Terminal stages (Survivorship) can be empty, but others shouldn't be
        if not stage.get("child_stage_ids") and not stage.get("after_stages"):
            if stage.get("name") != "Survival":
                warnings.append(f"Stage '{stage_id}' ({stage.get('name')}) is a DEAD END (no children, no after_stages).")

    # Report
    print("\n=== Validation Report ===")
    if errors:
        print(f"❌ Found {len(errors)} ERRORS:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("✅ No critical structure errors found.")
        
    if warnings:
        print(f"\n⚠️ Found {len(warnings)} WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
            
    if errors:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    validate_hierarchy()
