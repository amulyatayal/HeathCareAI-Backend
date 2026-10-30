"""Merge reviewer-approved AI recipe drafts from the review workbook into
data/recipe/recipes_full.json. Rows without an Approve decision are skipped."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import openpyxl

SHEET = "AI-drafted (to review)"
DECISIONS = {"approve": "Approve", "approve with edits": "Approve with edits", "reject": "Reject"}
APPLIED_MARK = "[applied]"


class ReviewError(Exception):
    """The workbook is in a state that must not be merged."""


@dataclass(frozen=True)
class ReviewRow:
    recipe_id: str
    decision: Optional[str]
    servings: int
    prep_time_mins: int
    cook_time_mins: int
    ingredients: List[str]
    instructions: List[str]
    allergens_uk: List[str]
    flags: str
    corrections: str
    reviewed_by: str
    review_date: str


def _lines(text: Optional[str], prefix: str) -> List[str]:
    out = []
    for line in (text or "").splitlines():
        line = re.sub(prefix, "", line.strip()).strip()
        if line:
            out.append(line)
    return out


def read_review_rows(path: Path) -> List[ReviewRow]:
    ws = openpyxl.load_workbook(path, read_only=True)[SHEET]
    rows = ws.iter_rows(values_only=True)
    next(rows)                      # group header
    headers = [str(h) for h in next(rows)]
    col = {h: i for i, h in enumerate(headers)}
    out: List[ReviewRow] = []
    for values in rows:
        get = lambda h: values[col[h]]
        rid = get("Recipe ID")
        if not rid:
            continue
        raw = str(get("Decision") or "").strip().lower()
        if raw and raw not in DECISIONS:
            raise ReviewError(f"{rid}: Decision '{get('Decision')}' is not Approve, Approve with edits or Reject")
        decision = DECISIONS.get(raw)
        reviewer = str(get("Reviewed by") or "").strip()
        if decision in ("Approve", "Approve with edits") and not reviewer:
            raise ReviewError(f"{rid}: approved but 'Reviewed by' is empty")
        allergens = [a.strip().lower() for a in re.split(r"[,\n]", str(get("Allergens in the AI ingredients") or "")) if a.strip()]
        out.append(ReviewRow(
            recipe_id=rid, decision=decision,
            servings=int(get("Servings")), prep_time_mins=int(get("Prep (min)")), cook_time_mins=int(get("Cook (min)")),
            ingredients=_lines(get("Ingredients"), r"^[•\-\*]\s*"),
            instructions=_lines(get("Method"), r"^\d+[.)]\s*"),
            allergens_uk=[a for a in allergens if a != "none"],
            flags=str(get("Flags for the reviewer") or ""),
            corrections=str(get("Corrections (write the corrected text)") or "").strip(),
            reviewed_by=reviewer, review_date=str(get("Date") or "").strip()[:10],
        ))
    return out


import argparse
import copy
import json
from datetime import datetime, timezone

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
RECIPES = REPO_ROOT / "data" / "recipe" / "recipes_full.json"
SCHEMA = REPO_ROOT / "data" / "recipe" / "recipes_full.schema.json"
_TO_APP = {"crustaceans": "shellfish", "molluscs": "shellfish", "peanuts": "nuts",
           "soya": "soy", "milk": "dairy", "eggs": "egg", "cereals containing gluten": "gluten",
           "tree nuts": "nuts", "shell fish": "shellfish"}
_UK_LABEL = {"crustaceans": "crustaceans (shellfish)", "molluscs": "molluscs (shellfish)",
             "soya": "soy", "milk": "dairy", "eggs": "egg", "cereals containing gluten": "gluten",
             "tree nuts": "nuts", "shell fish": "shellfish"}
_KNOWN_UK = {"gluten", "dairy", "nuts", "egg", "fish", "soy", "celery", "sesame", "peanuts",
             "crustaceans", "molluscs", "lupin", "sulphites", "mustard"} | set(_TO_APP)


def to_app_allergens(uk: List[str]) -> List[str]:
    return sorted({_TO_APP.get(a, a) for a in uk})


def allergen_info(uk: List[str], flags: str) -> str:
    parts = ", ".join(_UK_LABEL.get(a, a) for a in sorted(uk))
    text = f"Contains {parts}." if parts else "None of the 14 UK allergens."
    if "POSSIBLE SULPHITES" in flags:
        text += " May contain sulphites (check labels)."
    return text


def _recompute_stats(doc: dict) -> None:
    recs = doc["recipes"]
    complete = sum(1 for r in recs if r.get("has_full_recipe"))
    doc["statistics"].update(total_recipes=len(recs), complete_recipes=complete,
                             metadata_only_recipes=len(recs) - complete,
                             with_images=sum(1 for r in recs if r.get("image")))


def merge(doc: dict, rows: List[ReviewRow]) -> tuple[dict, dict]:
    new = copy.deepcopy(doc)
    by_id = {r["recipe_id"]: r for r in new["recipes"]}
    counts = {"merged": 0, "pending": 0, "rejected": 0}
    for row in rows:
        if row.decision is None:
            counts["pending"] += 1
            continue
        if row.decision == "Reject":
            counts["rejected"] += 1
            continue
        if row.decision == "Approve with edits" and not row.corrections.startswith(APPLIED_MARK):
            raise ReviewError(f"{row.recipe_id}: corrections not applied to the recipe cells")
        unknown = sorted(set(row.allergens_uk) - _KNOWN_UK)
        if unknown:
            raise ReviewError(f"{row.recipe_id}: unrecognised allergen '{unknown[0]}'")
        rec = by_id.get(row.recipe_id)
        if rec is None:
            raise ReviewError(f"{row.recipe_id}: not found in recipes_full.json")
        rec.update(
            ingredients=row.ingredients, instructions=row.instructions, has_full_recipe=True,
            servings=row.servings, prep_time_mins=row.prep_time_mins, cook_time_mins=row.cook_time_mins,
            allergens=to_app_allergens(row.allergens_uk), allergen_info=allergen_info(row.allergens_uk, row.flags),
            data_source="AI-drafted from the UK Diet and Supplementary Recipe Book entry; clinically reviewed",
            review={"decision": row.decision, "reviewed_by": row.reviewed_by, "date": row.review_date},
        )
        counts["merged"] += 1
    _recompute_stats(new)
    return new, counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    doc = json.loads(RECIPES.read_text())
    new, counts = merge(doc, read_review_rows(args.workbook))
    jsonschema.validate(new, json.loads(SCHEMA.read_text()))
    print(f"merged={counts['merged']} pending={counts['pending']} rejected={counts['rejected']}")
    if args.dry_run or new["recipes"] == doc["recipes"]:
        return
    new.update(version="1.1", generated_at=datetime.now(timezone.utc).isoformat(),
               generator="parse_recipes.py + apply_recipe_review.py")
    RECIPES.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
