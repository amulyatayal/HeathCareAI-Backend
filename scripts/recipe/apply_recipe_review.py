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
