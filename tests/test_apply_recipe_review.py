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


from scripts.recipe.apply_recipe_review import (  # noqa: E402
    to_app_allergens, allergen_info, merge, ReviewRow,
)


def rr(**kw) -> ReviewRow:
    base = dict(recipe_id="recipe-100", decision="Approve", servings=4, prep_time_mins=10, cook_time_mins=20,
                ingredients=["1 onion"], instructions=["Chop."], allergens_uk=["celery"], flags="",
                corrections="", reviewed_by="J. Patel RD", review_date="2026-11-01")
    base.update(kw)
    return ReviewRow(**base)


def doc_with(rid="recipe-100") -> dict:
    return {"version": "1.0", "generated_at": "x", "generator": "parse_recipes.py", "source": "s", "sections": [],
            "statistics": {"total_recipes": 1, "complete_recipes": 0, "metadata_only_recipes": 1, "with_images": 0, "categories_covered": []},
            "recipes": [{"recipe_id": rid, "title": "Test Soup", "meal_type": "soup", "dietary_tags": ["vegan"],
                         "allergens": [], "allergen_info": "None", "ingredients": [], "instructions": [],
                         "has_full_recipe": False, "nutrition": {}, "servings": None,
                         "prep_time_mins": None, "cook_time_mins": None, "image": None}]}


def test_shellfish_mapping():
    assert to_app_allergens(["crustaceans", "molluscs", "peanuts", "celery"]) == ["celery", "nuts", "shellfish"]


def test_allergen_info_keeps_uk_detail_and_sulphites():
    s = allergen_info(["crustaceans", "gluten"], flags="POSSIBLE SULPHITES: dried apricots")
    assert s == "Contains crustaceans (shellfish), gluten. May contain sulphites (check labels)."


def test_approved_row_completes_recipe():
    new, counts = merge(doc_with(), [rr()])
    r = new["recipes"][0]
    assert r["ingredients"] == ["1 onion"] and r["has_full_recipe"] is True
    assert r["review"] == {"decision": "Approve", "reviewed_by": "J. Patel RD", "date": "2026-11-01"}
    assert new["statistics"]["complete_recipes"] == 1 and counts["merged"] == 1


def test_pending_and_rejected_rows_unchanged():
    d = doc_with()
    new, counts = merge(d, [rr(decision=None)])
    assert new["recipes"][0]["ingredients"] == [] and counts["pending"] == 1
    new, counts = merge(d, [rr(decision="Reject")])
    assert new["recipes"][0]["ingredients"] == [] and counts["rejected"] == 1


def test_unapplied_edits_refused():
    with pytest.raises(ReviewError, match="not applied"):
        merge(doc_with(), [rr(decision="Approve with edits", corrections="Ingredients: 2 onions")])


def test_idempotent():
    once, _ = merge(doc_with(), [rr()])
    twice, _ = merge(once, [rr()])
    assert once["recipes"] == twice["recipes"] and once["statistics"] == twice["statistics"]


def test_shellfish_filter_end_to_end():
    from services.recipe_service import _normalise_allergen
    new, _ = merge(doc_with(), [rr(allergens_uk=["molluscs"])])
    assert "shellfish" in {_normalise_allergen(a) for a in new["recipes"][0]["allergens"]}


def test_synonyms_map_to_app_vocabulary():
    assert to_app_allergens(["soya", "milk", "eggs"]) == ["dairy", "egg", "soy"]
    assert to_app_allergens(["cereals containing gluten", "tree nuts", "shell fish"]) == ["gluten", "nuts", "shellfish"]


def test_unknown_allergen_on_approved_row_fails_closed():
    with pytest.raises(ReviewError, match=r"recipe-100.*kiwi"):
        merge(doc_with(), [rr(allergens_uk=["kiwi"])])


def test_unknown_allergen_on_pending_row_ignored():
    _, counts = merge(doc_with(), [rr(decision=None, allergens_uk=["kiwi"])])
    assert counts["pending"] == 1


def test_known_vocabulary_maps_into_app_vocabulary():
    from scripts.recipe.apply_recipe_review import _KNOWN_UK
    app = {"dairy", "gluten", "nuts", "soy", "egg", "fish", "shellfish", "sesame", "celery", "mustard", "lupin", "sulphites"}
    assert set(to_app_allergens(sorted(_KNOWN_UK | {"mustard"}))) <= app
