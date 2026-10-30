from pathlib import Path
import openpyxl
import pytest
from scripts.recipe.apply_recipe_review import read_review_rows, ReviewError

HEADERS = ["Recipe ID", "Title", "Section", "Diet tag", "Allergens listed in book",
           "kcal / serving", "Protein g", "Book description", "Status", "Servings",
           "Prep (min)", "Cook (min)", "Ingredients", "Method",
           "Allergens in the AI ingredients", "Flags for the reviewer", "Decision",
           "Corrections (write the corrected text)", "Comments", "Reviewed by", "Date"]

def make_book(tmp_path: Path, rows: list[dict]) -> Path:
    wb = openpyxl.Workbook()
    wb.active.title = "Read me"
    ws = wb.create_sheet("AI-drafted (to review)")
    ws.append(["group header row"])
    ws.append(HEADERS)
    for r in rows:
        ws.append([r.get(h) for h in HEADERS])
    wb.create_sheet("Complete in book")
    p = tmp_path / "review.xlsx"
    wb.save(p)
    return p

def row(**kw) -> dict:
    base = {"Recipe ID": "recipe-100", "Title": "Test Soup", "Servings": 4,
            "Prep (min)": 10, "Cook (min)": 20,
            "Ingredients": "• 1 onion\n• 500ml vegetable stock",
            "Method": "1. Chop the onion.\n2. Simmer in stock for 20 minutes.",
            "Allergens in the AI ingredients": "celery"}
    base.update(kw)
    return base

def test_reads_decision_case_insensitively(tmp_path):
    p = make_book(tmp_path, [row(Decision=" approve ", **{"Reviewed by": "J. Patel RD", "Date": "2026-11-01"})])
    [r] = read_review_rows(p)
    assert r.decision == "Approve"
    assert r.ingredients == ["1 onion", "500ml vegetable stock"]
    assert r.instructions == ["Chop the onion.", "Simmer in stock for 20 minutes."]

def test_blank_decision_is_pending(tmp_path):
    [r] = read_review_rows(make_book(tmp_path, [row()]))
    assert r.decision is None

def test_unknown_decision_aborts_with_row_id(tmp_path):
    with pytest.raises(ReviewError, match="recipe-100"):
        read_review_rows(make_book(tmp_path, [row(Decision="Maybe")]))

def test_approved_without_reviewer_name_aborts(tmp_path):
    with pytest.raises(ReviewError, match="Reviewed by"):
        read_review_rows(make_book(tmp_path, [row(Decision="Approve")]))
