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
    # Build hierarchical stage ID from Sub Stage levels
    group = row.get('Stage Group', '').strip()
    level0 = row.get('Sub Stage Level 0', '').strip()
    level1 = row.get('Sub Stage Level 1', '').strip()
    level2 = row.get('Sub Stage Level 2', '').strip()
    
    name = row.get('Name', '').strip()
    
    # Skip rows without a name
    if not name:
        return None
    
    # Build stage_id from hierarchy (e.g., "2.1.1")
    parts = [p for p in [group, level0, level1, level2] if p]
    if not parts:
        return None
    stage_id = '.'.join(parts)
    
    # Clean up multiline name
    name = ' '.join(name.split())
    
    # Parse description
    description = row.get('Description', '').strip()
    description = ' '.join(description.split())  # Clean multiline
    
    # For now, use simple transition logic (can enhance with CSV data later)
    before_stages = []
    after_stages = []
    
    # Parse patient facing flag - assume all are patient facing
    is_patient_facing = True
    
    # ===== V2.1: Extract Verification Questions =====
    verification_questions = []
    questions_raw = row.get('Patient Facing Questions', '').strip()
    if questions_raw:
        # Split by newlines or semicolons
        questions = [q.strip() for q in questions_raw.replace('\n', ';').split(';') if q.strip()]
        verification_questions = questions
    
    # ===== V2.1: Extract Safety Triggers =====
    # General safety keywords from description
    safety_keywords = [
        'fever', 'bleeding', 'severe pain', 'chest pain', 'infection',
        'swelling', 'redness', 'discharge', 'shortness of breath',
        'emergency', 'urgent', 'numbness', 'weakness', 'confusion'
    ]
    safety_triggers = []
    description_lower = description.lower()
    for keyword in safety_keywords:
        if keyword in description_lower:
            safety_triggers.append(keyword)
    
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
        "transition_notes": None,
        "is_patient_facing": is_patient_facing,
        "verification_questions": verification_questions,
        "safety_triggers": safety_triggers,
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
    project_root = script_dir.parent.parent
    csv_path = project_root / "data" / "Breast cancer stages" / "Knowledge Base Bank - BreastCancerStagesProcessed.csv"
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
