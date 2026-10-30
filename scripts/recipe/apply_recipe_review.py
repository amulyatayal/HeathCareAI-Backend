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
    allergens_blank: bool
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
        review_date = str(get("Date") or "").strip()[:10]
        if decision in ("Approve", "Approve with edits") and not review_date:
            raise ReviewError(f"{rid}: approved but 'Date' is empty")
        allergen_cell = str(get("Allergens in the AI ingredients") or "")
        allergens = [a.strip().lower() for a in re.split(r"[,\n]", allergen_cell) if a.strip()]
        out.append(ReviewRow(
            recipe_id=rid, decision=decision,
            servings=int(get("Servings")), prep_time_mins=int(get("Prep (min)")), cook_time_mins=int(get("Cook (min)")),
            ingredients=_lines(get("Ingredients"), r"^[•\-\*]\s*"),
            instructions=_lines(get("Method"), r"^\d+[.)]\s*"),
            allergens_uk=[a for a in allergens if a != "none"],
            allergens_blank=not allergen_cell.strip(),
            flags=str(get("Flags for the reviewer") or ""),
            corrections=str(get("Corrections (write the corrected text)") or "").strip(),
            reviewed_by=reviewer, review_date=review_date,
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


def allergen_info(uk: List[str], flags: str, book_extra: Optional[List[str]] = None) -> str:
    parts = ", ".join(_UK_LABEL.get(a, a) for a in sorted(uk))
    text = f"Contains {parts}." if parts else "None of the 14 UK allergens."
    if "POSSIBLE SULPHITES" in flags:
        text += " May contain sulphites (check labels)."
    if book_extra:
        text += f" The recipe book also lists: {', '.join(sorted(book_extra))}."
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
    seen = set()
    for row in rows:
        if row.recipe_id in seen:
            raise ReviewError(f"{row.recipe_id}: duplicate Recipe ID in the workbook")
        seen.add(row.recipe_id)
    for row in rows:
        rec = by_id.get(row.recipe_id)
        if row.decision is None or row.decision == "Reject":
            if rec is not None and "review" in rec:
                raise ReviewError(
                    f"{row.recipe_id}: approval withdrawn but recipe is already merged; "
                    "restore it from git before re-running")
            counts["pending" if row.decision is None else "rejected"] += 1
            continue
        if row.decision == "Approve with edits" and not row.corrections.startswith(APPLIED_MARK):
            raise ReviewError(f"{row.recipe_id}: corrections not applied to the recipe cells")
        unknown = sorted(set(row.allergens_uk) - _KNOWN_UK)
        if unknown:
            raise ReviewError(f"{row.recipe_id}: unrecognised allergen '{unknown[0]}'")
        if row.allergens_blank:
            raise ReviewError(
                f"{row.recipe_id}: allergen cell is blank; write 'none' if the recipe has no allergens")
        if not row.review_date:
            raise ReviewError(f"{row.recipe_id}: approved but Date is empty")
        if rec is None:
            raise ReviewError(f"{row.recipe_id}: not found in recipes_full.json")
        if rec.get("has_full_recipe") and "review" not in rec:
            raise ReviewError(f"{row.recipe_id}: recipe is complete in the book; refusing to overwrite")
        # Book allergens come from the pre-merge state so a re-merge is identical.
        if "review" in rec:
            book = list(rec["review"]["book_allergens"])
        else:
            book = list(rec.get("allergens") or [])
        ai_app = set(to_app_allergens(row.allergens_uk))
        rec.update(
            ingredients=row.ingredients, instructions=row.instructions, has_full_recipe=True,
            servings=row.servings, prep_time_mins=row.prep_time_mins, cook_time_mins=row.cook_time_mins,
            allergens=sorted(set(book) | ai_app),
            allergen_info=allergen_info(row.allergens_uk, row.flags, sorted(set(book) - ai_app)),
            data_source="AI-drafted from the UK Diet and Supplementary Recipe Book entry; clinically reviewed",
            review={"decision": row.decision, "reviewed_by": row.reviewed_by, "date": row.review_date,
                    "book_allergens": sorted(book)},
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
    print("Wrote recipes_full.json. Next: re-index search "
          "(scripts/opensearch/ingest_recipes.py --recreate) and restart the API.")


if __name__ == "__main__":
    main()
