"""
Parse the UK Diet & Supplementary recipe book PDF into structured JSON.

The book holds 310 recipes (001-310) across 8 sections. Every recipe carries
metadata + a full nutrition table + clinical-significance text + a source line.
Only ~37 recipes additionally include an INGREDIENTS list and METHOD steps; the
remaining ~273 stop after the nutrition table. Per project rule, we never invent
ingredients/methods - absent ones are left empty.

Output: data/recipe/recipes_full.json  (one object per recipe, schema below)
Images: data/recipe/images/recipe-NNN.<ext>  (only the ~25 that are embedded)

Usage:
    python scripts/recipe/parse_recipes.py --pdf "/path/UK Diet ... .pdf"
    python scripts/recipe/parse_recipes.py --pdf "..." --no-images
"""

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_NOW_ISO = datetime.now(timezone.utc).isoformat()

import PyPDF2

try:
    import fitz  # PyMuPDF — reliable image extraction (PyPDF2 mangles masked PNGs)
    _HAVE_FITZ = True
except ImportError:
    _HAVE_FITZ = False

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = REPO_ROOT / "data" / "recipe" / "recipes_full.json"
IMG_DIR = REPO_ROOT / "data" / "recipe" / "images"

# --------------------------------------------------------------------------
# Section -> category map (recipe-number ranges, from the SECTION headers)
# --------------------------------------------------------------------------
SECTION_RANGES: List[Tuple[int, int, str, str]] = [
    (1, 40, "breakfast", "Breakfast"),
    (41, 85, "soup", "Soups"),
    (86, 165, "main_vegetarian", "Main Meals — Vegetarian"),
    (166, 200, "main_non_vegetarian", "Main Meals — Non-Vegetarian"),
    (201, 230, "salad", "Salads & Light Meals"),
    (231, 260, "snack", "Snacks & Dips"),
    (261, 285, "smoothie", "Smoothies & Drinks"),
    (286, 310, "dessert", "Desserts"),
]
CATEGORY_EMOJI = {
    "breakfast": "\U0001F963",          # bowl with spoon
    "soup": "\U0001F372",               # pot of food
    "main_vegetarian": "\U0001F957",    # green salad
    "main_non_vegetarian": "\U0001F357",  # poultry leg
    "salad": "\U0001F96C",              # leafy green
    "snack": "\U0001F968",              # pretzel
    "smoothie": "\U0001F964",           # cup with straw
    "dessert": "\U0001F370",            # shortcake
}


def category_for(num: int) -> Tuple[str, str]:
    for lo, hi, slug, label in SECTION_RANGES:
        if lo <= num <= hi:
            return slug, label
    return "uncategorized", "Uncategorized"


# --------------------------------------------------------------------------
# Allergen derivation (best-effort, keyword based)
# Source has no explicit allergen list; we infer from name + ingredients +
# clinical text. Plant milks are guarded so "oat/soya milk" is not flagged dairy.
# --------------------------------------------------------------------------
PLANT_MILK = re.compile(r"(oat|soya|soy|almond|coconut|rice|cashew|hemp)\s*milk", re.I)
ALLERGEN_KEYWORDS: Dict[str, List[str]] = {
    "gluten": ["wheat", "barley", "rye", "bread", "flour", "pasta", "couscous",
               "bulgur", "seitan", "breadcrumb", "wholemeal", "oat", "oats",
               "porridge", "cracker", "noodle", "chapati", "naan", "pastry"],
    "dairy": ["cheese", "butter", "cream", "ghee", "paneer", "yoghurt", "yogurt",
              "custard", "whey", "casein"],
    "nuts": ["almond", "walnut", "cashew", "pecan", "hazelnut", "pistachio",
             "peanut", "macadamia", "brazil nut", "nut "],
    "soy": ["soy", "soya", "tofu", "edamame", "miso", "tempeh"],
    "egg": ["egg"],
    "fish": ["salmon", "mackerel", "tuna", "sardine", "cod", "haddock",
             "anchovy", "trout", "fish"],
    "shellfish": ["prawn", "shrimp", "crab", "lobster", "mussel", "oyster",
                  "scallop", "squid"],
    "sesame": ["sesame", "tahini"],
}


def derive_allergens(text: str) -> List[str]:
    low = text.lower()
    found = set()
    # dairy: any dairy keyword, OR the word "milk" that is NOT a plant milk
    if any(k in low for k in ALLERGEN_KEYWORDS["dairy"]):
        found.add("dairy")
    for m in re.finditer(r"milk", low):
        seg = low[max(0, m.start() - 12):m.start() + 4]
        if not PLANT_MILK.search(seg):
            found.add("dairy")
            break
    for allergen, kws in ALLERGEN_KEYWORDS.items():
        if allergen == "dairy":
            continue
        if any(k in low for k in kws):
            found.add(allergen)
    return sorted(found)


# --------------------------------------------------------------------------
# Nutrition table parsing
# --------------------------------------------------------------------------
NUTRIENT_LABELS = [
    ("energy_kcal", "Energy"),
    ("protein_g", "Protein"),
    ("carbohydrates_g", "Carbohydrates"),
    ("dietary_fibre_g", "Dietary Fiber"),
    ("total_fat_g", "Total Fat"),
    ("calcium_mg", "Calcium"),
    ("iron_mg", "Iron"),
    ("magnesium_mg", "Magnesium"),
    ("potassium_mg", "Potassium"),
    ("folate_ug", "Folate"),
    ("vitamin_c_mg", "Vitamin C"),
    ("stage_suitability", "Stage Suitability"),
]
AMOUNT_RE = re.compile(
    r"^\s*(~?\s*[\d.,]+(?:\s*[–-]\s*[\d.,]+)?\s*(?:kcal|g|mg|µg|μg|mcg)?)",
    re.I,
)
SOURCES_RE = re.compile(r"\[([^\]]+)\]")


def parse_nutrition(block: str) -> Dict[str, dict]:
    """Slice the nutrition region by the known nutrient labels (in order)."""
    start = block.find("Nutritional Information")
    end = block.find("Recipe Source:")
    if start == -1:
        return {}
    region = block[start:end if end != -1 else len(block)]

    # locate each label's position
    positions = []
    for key, label in NUTRIENT_LABELS:
        idx = region.find(label)
        if idx != -1:
            positions.append((idx, key, label))
    positions.sort()

    nutrition: Dict[str, dict] = {}
    for i, (idx, key, label) in enumerate(positions):
        seg_start = idx + len(label)
        seg_end = positions[i + 1][0] if i + 1 < len(positions) else len(region)
        seg = region[seg_start:seg_end].strip()

        if key == "stage_suitability":
            # "I, II, III, IV  Recipe validated ..."
            m = re.match(r"([IVX,\s]+)\s+(.*)", seg)
            amount = (m.group(1).strip() if m else seg[:20]).rstrip(",")
            target = m.group(2).strip() if m else ""
        else:
            am = AMOUNT_RE.match(seg)
            amount = re.sub(r"\s+", " ", am.group(1)).strip() if am else ""
            target = seg[am.end():].strip() if am else seg
        sources = [s.strip() for s in SOURCES_RE.findall(target)]
        target_clean = SOURCES_RE.sub("", target).strip().rstrip(";").strip()
        nutrition[key] = {
            "amount": amount,
            "daily_target": target_clean,
            "sources": sources,
        }
    return nutrition


def kcal_int(nutrition: Dict[str, dict]) -> int:
    raw = nutrition.get("energy_kcal", {}).get("amount", "")
    m = re.search(r"\d+", raw.replace(",", ""))
    return int(m.group()) if m else 0


# --------------------------------------------------------------------------
# Ingredients / method (present for only ~37 recipes)
# --------------------------------------------------------------------------
# The DOCX->PDF export mangles the trailing "Source:" footer into "Sourc e:"
# (stray space). Tolerate any internal spacing so method/ingredient capture
# stops before it instead of swallowing the footer into the last item.
_SOURCE_BOUNDARY = r"Sourc\s*e\s*:"


def parse_ingredients(block: str) -> List[str]:
    # Case-sensitive: the recipe header is always uppercase "INGREDIENTS:".
    # (A case-insensitive match would catch the word "ingredients" in prose.)
    m = re.search(rf"INGREDIENTS\s*:?(.*?)(?:METHOD\s*:|{_SOURCE_BOUNDARY}|$)",
                  block, re.S)
    if not m:
        return []
    raw = m.group(1)
    items = [re.sub(r"\s+", " ", x).strip(" •●-").strip()
             for x in re.split(r"[•●]", raw)]
    return [x for x in items if len(x) > 1]


def parse_method(block: str) -> List[str]:
    # Case-sensitive: the recipe header is always uppercase "METHOD:". A
    # case-insensitive match would catch lowercase "method" in back-matter
    # (e.g. the references appendix after the final recipe).
    m = re.search(rf"METHOD\s*:?(.*?)(?:{_SOURCE_BOUNDARY}|─{{3,}}|$)", block, re.S)
    if not m:
        return []
    raw = m.group(1)
    steps = re.split(r"(?:^|\s)(?=\d+\.\s)", raw)
    out = []
    for s in steps:
        s = re.sub(r"^\s*\d+\.\s*", "", re.sub(r"\s+", " ", s)).strip()
        if len(s) > 3:
            out.append(s)
    return out


# --------------------------------------------------------------------------
# Header (name / meal-type / diet / stages / side-effect support / clinical)
# --------------------------------------------------------------------------
HEADER_RE = re.compile(
    r"RECIPE\s+0*(\d{1,3})\s+"
    r"(?P<name>[A-Z0-9À-ſ][A-Z0-9À-ſ ,'&()–/.+-]+?)\s+"
    r"(?P<mtype>[A-Z][a-z][A-Za-z &—-]*?)\s*\|\s*"
    r"(?P<diet>[A-Za-z —/&-]+?)\s*\|\s*"
    r"Stages?\s*:\s*(?P<stages>[IVX0-9,\s]+?)\s+"
    r"Side-Effect\s+Support\s*:\s*(?P<se>.+?)\s+"
    r"CLINICAL\s+SIGNIFICANCE",
    re.S,
)


def parse_stages(raw: str) -> List[str]:
    return [s.strip() for s in re.split(r"[,\s]+", raw.strip()) if s.strip()]


def parse_source(block: str) -> dict:
    m = re.search(r"Recipe Source\s*:\s*(.+?)\s*\|\s*(https?://\S+)", block)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        url = m.group(2).strip().rstrip(".,")
        return {"title": title, "url": url}
    m2 = re.search(r"Recipe Source\s*:\s*(.+?)(?:─|$)", block)
    return {"title": re.sub(r"\s+", " ", m2.group(1)).strip() if m2 else "", "url": ""}


# --------------------------------------------------------------------------
# PDF -> concatenated text with page offset map
# --------------------------------------------------------------------------
def load_text(pdf_path: Path) -> Tuple[str, List[Tuple[int, int]]]:
    reader = PyPDF2.PdfReader(str(pdf_path))
    chunks: List[str] = []
    offsets: List[Tuple[int, int]] = []  # (char_offset_start, page_number)
    cursor = 0
    sep = " \n "
    for i, page in enumerate(reader.pages, start=1):
        t = re.sub(r"\s+", " ", (page.extract_text() or "")).strip()
        offsets.append((cursor, i))
        chunks.append(t)
        cursor += len(t) + len(sep)
    return sep.join(chunks), offsets


def page_for_offset(offset: int, offsets: List[Tuple[int, int]]) -> int:
    page = 1
    for off, pg in offsets:
        if off <= offset:
            page = pg
        else:
            break
    return page


# --------------------------------------------------------------------------
# Image extraction
# --------------------------------------------------------------------------
def extract_images(pdf_path: Path, recipe_pages: Dict[int, int]) -> Dict[int, str]:
    """Save embedded recipe photos with PyMuPDF; map recipe_number -> image path.

    PyPDF2 mangles these ICC/masked PNGs to solid black, so PyMuPDF is required.
    recipe_pages maps page_number -> recipe_number active on that page.
    """
    if not _HAVE_FITZ:
        logger.warning("PyMuPDF (fitz) not installed — skipping images. "
                       "Run: pip install pymupdf")
        return {}
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    out: Dict[int, str] = {}
    for pno in range(1, len(doc) + 1):
        imgs = doc[pno - 1].get_images(full=True)
        if not imgs:
            continue
        recipe_num = recipe_pages.get(pno)
        if recipe_num is None:
            continue
        xref = imgs[0][0]  # one photo per recipe page
        try:
            pix = fitz.Pixmap(doc, xref)
            # Normalise to plain RGB (drop alpha / ICC / CMYK)
            if pix.alpha or (pix.colorspace and pix.colorspace.name != "DeviceRGB"):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            fname = f"recipe-{recipe_num:03d}.png"
            pix.save(str(IMG_DIR / fname))
            out[recipe_num] = f"images/{fname}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("  image save failed for recipe %s: %s", recipe_num, exc)
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def first_sentence(text: str, limit: int = 180) -> str:
    s = re.split(r"(?<=[.!?])\s", text.strip())[0] if text.strip() else ""
    return (s[:limit].rstrip() + "…") if len(s) > limit else s


# --------------------------------------------------------------------------
# Unified-schema helpers (align field names/shape with nutrition_kb.json)
# --------------------------------------------------------------------------
# Map the book's 8 sections to a simple meal_type vocabulary (nutrition_kb uses
# values like breakfast/lunch/dinner/soup/smoothie). Mains have no time-of-day in
# the source, so they collapse to "main".
MEAL_TYPE_MAP = {
    "breakfast": "breakfast",
    "soup": "soup",
    "main_vegetarian": "main",
    "main_non_vegetarian": "main",
    "salad": "salad",
    "snack": "snack",
    "smoothie": "smoothie",
    "dessert": "dessert",
}
_STAGE_NAMES = {"I": "Stage I", "II": "Stage II", "III": "Stage III", "IV": "Stage IV"}


def _first_number(amount: str):
    """Lower-bound integer from a nutrition amount like '~59–66 g' -> 59."""
    if not amount:
        return None
    m = re.search(r"\d+(?:\.\d+)?", amount.replace(",", ""))
    if not m:
        return None
    val = float(m.group())
    return int(val) if val.is_integer() else val


def flat_nutrition(detail: Dict[str, dict], calories: int) -> Dict[str, Any]:
    """Derive nutrition_kb-style flat scalars from the rich nutrition_detail.

    sugar_g and sodium_mg are null: the source nutrition table has no rows for
    them (it lists fibre, fat, calcium, iron, magnesium, potassium, folate, vit C).
    """
    def amt(key):
        return _first_number(detail.get(key, {}).get("amount", ""))
    return {
        "calories_per_serving": calories or None,
        "protein_g": amt("protein_g"),
        "fiber_g": amt("dietary_fibre_g"),
        "fat_g": amt("total_fat_g"),
        "carbs_g": amt("carbohydrates_g"),
        "sugar_g": None,   # not provided in source
        "sodium_mg": None,  # not provided in source
    }


def allergen_info_str(allergens: List[str]) -> str:
    """nutrition_kb-style summary string from the structured allergen list."""
    return "Contains " + ", ".join(allergens) if allergens else "None"


def parse(pdf_path: Path, with_images: bool = True) -> List[dict]:
    alltext, offsets = load_text(pdf_path)
    matches = list(re.finditer(r"RECIPE\s+0*(\d{1,3})\b", alltext))
    logger.info("Found %d recipe anchors", len(matches))

    # recipe_number -> page (header page) and page -> recipe_number coverage
    recipe_header_page: Dict[int, int] = {}
    block_spans: List[Tuple[int, int, int]] = []  # (num, start, end)
    for i, m in enumerate(matches):
        num = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(alltext)
        block_spans.append((num, start, end))
        recipe_header_page[num] = page_for_offset(start, offsets)

    # page -> recipe number (a page belongs to the recipe whose block covers it)
    page_to_recipe: Dict[int, int] = {}
    for num, start, end in block_spans:
        p_start = page_for_offset(start, offsets)
        p_end = page_for_offset(end - 1, offsets)
        for pg in range(p_start, p_end + 1):
            page_to_recipe.setdefault(pg, num)

    images = extract_images(pdf_path, page_to_recipe) if with_images else {}
    logger.info("Extracted %d embedded images", len(images))

    recipes: List[dict] = []
    incomplete = 0
    for num, start, end in block_spans:
        block = alltext[start:end]
        # The final recipe's span runs to EOF and would swallow the book's
        # back-matter (REFERENCES bibliography). Cut the block at the first
        # back-matter header that appears after the recipe's source footer.
        bm = re.search(r"\bREFERENCES\b", block)
        if bm and bm.start() > block.find("Recipe Source:"):
            block = block[:bm.start()]
        hm = HEADER_RE.search(block)
        if not hm:
            logger.warning("  header parse failed for recipe %03d", num)
            name = mtype = diet = se_raw = ""
            stages: List[str] = []
            clinical = ""
        else:
            name = re.sub(r"\s+", " ", hm.group("name")).strip().title()
            mtype = re.sub(r"\s+", " ", hm.group("mtype")).strip()
            diet = re.sub(r"\s+", " ", hm.group("diet")).strip()
            stages = parse_stages(hm.group("stages"))
            se_raw = hm.group("se")
            cm = re.search(
                r"CLINICAL\s+SIGNIFICANCE\s*&?\s*EVIDENCE\s+BASE\s*(.*?)\s*"
                r"Nutritional Information",
                block, re.S,
            )
            clinical = re.sub(r"\s+", " ", cm.group(1)).strip() if cm else ""

        side_effects = [s.strip().lower() for s in re.split(r",", se_raw) if s.strip()]
        nutrition_detail = parse_nutrition(block)
        ingredients = parse_ingredients(block)
        steps = parse_method(block)
        cat_slug, cat_label = category_for(num)
        source = parse_source(block)
        source["page"] = recipe_header_page.get(num)
        calories = kcal_int(nutrition_detail)
        diets = [d.strip().lower() for d in re.split(r"[/,]", diet) if d.strip()]
        allergens = derive_allergens(" ".join([name] + ingredients + [clinical]))

        if not ingredients and not steps:
            incomplete += 1

        # Unified schema — nutrition_kb field names adopted where the concept
        # matches; book-specific richness retained alongside.
        record = {
            # --- identity & classification ---
            "recipe_id": f"recipe-{num:03d}",       # was "id"  (nutrition_kb: recipe_id)
            "recipe_number": num,
            "title": name,                           # was "name" (nutrition_kb: title)
            "emoji": CATEGORY_EMOJI.get(cat_slug, "\U0001F37D"),
            "meal_type": MEAL_TYPE_MAP.get(cat_slug, cat_slug),
            "cuisine_type": None,                    # not specified in source
            "category": cat_slug,                    # book section slug
            "category_label": cat_label,
            # --- dietary / health ---
            "dietary_tags": diets,                   # was "diets" (nutrition_kb: dietary_tags)
            "allergens": allergens,                  # structured list (for filtering)
            "allergen_info": allergen_info_str(allergens),  # nutrition_kb-style summary
            "symptom_support": side_effects,         # was "side_effect_support"
            "texture_class": None,                   # not specified in source
            "stages": stages,                        # tumour stage I–IV (book-specific)
            "stage_display_names": [_STAGE_NAMES.get(s, s) for s in stages],
            # --- content ---
            "description": first_sentence(clinical),  # was "desc"
            "clinical_notes": clinical,              # was "clinical_significance"
            "ingredients": ingredients,
            "instructions": steps,                   # was "steps" (nutrition_kb: instructions)
            "tips": None,                            # not provided in source
            "has_full_recipe": bool(ingredients and steps),
            # --- servings & timing (not in source) ---
            "servings": None,
            "prep_time_mins": None,
            "cook_time_mins": None,
            # --- nutrition ---
            "nutrition": flat_nutrition(nutrition_detail, calories),  # nutrition_kb shape
            "nutrition_detail": nutrition_detail,    # rich per-nutrient evidence (book)
            # --- source & media ---
            "source": source,                        # recipe citation {title,url,page}
            "image": images.get(num),
            # --- provenance ---
            "created_at": _NOW_ISO,
            "data_source": "UK Diet and Supplementary Recipe Book (PDF)",
        }
        recipes.append(record)

    logger.info("Parsed %d recipes (%d complete with ingredients+method, %d metadata-only)",
                len(recipes), len(recipes) - incomplete, incomplete)
    return recipes


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse recipe book PDF -> JSON")
    ap.add_argument("--pdf", required=True, help="Path to the recipe book PDF")
    ap.add_argument("--out", default=str(OUT_JSON), help="Output JSON path")
    ap.add_argument("--no-images", action="store_true", help="Skip image extraction")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    recipes = parse(pdf_path, with_images=not args.no_images)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    complete = sum(1 for r in recipes if r["has_full_recipe"])
    with_images = sum(1 for r in recipes if r["image"])
    categories = sorted({r["category"] for r in recipes})

    # Top-level wrapper mirrors nutrition_kb.json (version/generated_at/generator/
    # source/statistics) so both knowledge files share one envelope shape.
    payload = {
        "version": "1.0",
        "generated_at": _NOW_ISO,
        "generator": "parse_recipes.py",
        "source": "UK Diet and Supplementary Recipe Book (PDF)",
        "source_file": pdf_path.name,
        "statistics": {
            "total_recipes": len(recipes),
            "complete_recipes": complete,
            "metadata_only_recipes": len(recipes) - complete,
            "with_images": with_images,
            "categories_covered": categories,
        },
        "sections": [
            {"slug": s, "label": lbl, "from": lo, "to": hi}
            for lo, hi, s, lbl in SECTION_RANGES
        ],
        "recipes": recipes,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    logger.info("Wrote %s (%d recipes)", out_path, len(recipes))


if __name__ == "__main__":
    main()
