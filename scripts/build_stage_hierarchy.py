#!/usr/bin/env python3
"""
Build Stage Hierarchy
Converts the Knowledge Base CSV into an optimized JSON file.

Run this script after updating the CSV to regenerate the JSON:
    python scripts/build_stage_hierarchy.py

The output JSON file is loaded by patient_stage_service.py at runtime
for fast access without CSV parsing.
"""

import csv
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any


def parse_csv_row(row: dict) -> Optional[Dict[str, Any]]:
    """Parse a CSV row into a stage dictionary."""
    stage_no = row.get('Stage No.', '').strip()
    sub_stage = row.get('Sub Stage', '').strip()
    name = row.get('Name', '').strip()
    
    # Skip rows without a name
    if not name:
        return None
    
    # Determine stage ID (prefer sub_stage if available)
    stage_id = sub_stage if sub_stage else stage_no
    if not stage_id:
        return None
    
    # Clean up multiline name
    name = ' '.join(name.split())
    
    # Parse description
    description = row.get('Description', '').strip()
    description = ' '.join(description.split())  # Clean multiline
    
    # Parse transition stages
    before_raw = row.get('Before Stage (can be multipl', '').strip()
    before_stages = [s.strip() for s in before_raw.split(',') if s.strip() and s.strip() != '<start>']
    
    after_raw = row.get('After Stage', '').strip()
    after_stages = [s.strip() for s in after_raw.split(',') if s.strip() and s.strip() != '<End of Pathways>']
    
    # Parse transition notes
    transition_notes = row.get('Transition notes from this stage to next stage', '').strip()
    
    # Parse patient facing flag
    patient_facing_raw = row.get('Patient Facing (Y/N)?', 'Y').strip().upper()
    is_patient_facing = patient_facing_raw != 'N'
    
    # Determine parent stage from ID structure
    parent_stage_id = get_parent_id(stage_id)
    
    return {
        "stage_id": stage_id,
        "name": name,
        "description": description,
        "parent_stage_id": parent_stage_id,
        "child_stage_ids": [],  # Will be populated later
        "before_stages": before_stages,
        "after_stages": after_stages,
        "transition_notes": transition_notes if transition_notes else None,
        "is_patient_facing": is_patient_facing,
    }


def get_parent_id(stage_id: str) -> Optional[str]:
    """Determine the parent stage ID from a stage ID."""
    if '.' not in stage_id:
        return None
    
    parts = stage_id.rsplit('.', 1)
    if parts[0]:
        return parts[0]
    return None


def build_relationships(stages: Dict[str, dict]) -> List[str]:
    """Build parent-child relationships and return root stage IDs."""
    root_stages = []
    
    for stage_id, stage in stages.items():
        parent_id = stage.get("parent_stage_id")
        
        if parent_id is None:
            root_stages.append(stage_id)
        elif parent_id in stages:
            parent = stages[parent_id]
            if stage_id not in parent["child_stage_ids"]:
                parent["child_stage_ids"].append(stage_id)
    
    return root_stages


def main():
    # Paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    csv_path = project_root / "data" / "Knowledge Base Bank - BreastCancerStages.csv"
    json_path = project_root / "data" / "stage_hierarchy.json"
    
    print(f"📂 Reading CSV: {csv_path}")
    
    if not csv_path.exists():
        print(f"❌ Error: CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Parse CSV
    stages = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            stage = parse_csv_row(row)
            if stage:
                stages[stage["stage_id"]] = stage
    
    print(f"   ✅ Parsed {len(stages)} stages")
    
    # Build relationships
    root_stages = build_relationships(stages)
    print(f"   ✅ Found {len(root_stages)} root stages")
    
    # Create output structure
    output = {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_file": csv_path.name,
        "total_stages": len(stages),
        "root_stage_ids": root_stages,
        "stages": stages,
    }
    
    # Write JSON
    print(f"📝 Writing JSON: {json_path}")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"   ✅ Generated {json_path.name}")
    print()
    print("🎉 Stage hierarchy built successfully!")
    print(f"   Stages: {len(stages)}")
    print(f"   Root stages: {root_stages[:5]}{'...' if len(root_stages) > 5 else ''}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
