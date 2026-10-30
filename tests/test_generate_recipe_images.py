"""Tests for recipe image generation script."""
import io
from pathlib import Path

import pytest
from PIL import Image

import base64
import json

from botocore.exceptions import ClientError

from scripts.recipe.generate_recipe_images import (
    build_prompt, save_jpeg, generate, _main_ingredients, _invoke, write_contact_sheet,
)


R = {
    "recipe_id": "recipe-100",
    "title": "Lentil Soup",
    "meal_type": "soup",
    "ingredients": ["200g red lentils", "1 onion", "1 carrot", "1 litre stock", "1 tsp cumin"],
    "image": None,
}


def test_prompt_is_food_only_and_uses_title_and_main_ingredients():
    """Test that build_prompt includes recipe title, ingredients, and safety disclaimers."""
    p = build_prompt(R)
    assert "Lentil Soup" in p and "red lentils" in p
    assert "no text" in p and "no people" in p


def test_save_jpeg_under_limit(tmp_path):
    """Test that save_jpeg encodes PNG to JPEG and respects size limits."""
    buf = io.BytesIO()
    Image.effect_noise((1024, 1024), 80).convert("RGB").save(buf, "PNG")
    n = save_jpeg(buf.getvalue(), tmp_path / "x.jpg", max_kb=300)
    assert n <= 300 * 1024 and Image.open(tmp_path / "x.jpg").size == (1024, 1024)


def test_save_jpeg_exceeds_limit_raises_valueerror(tmp_path):
    """Test that save_jpeg raises ValueError if image cannot fit in max_kb even at lowest quality."""
    buf = io.BytesIO()
    Image.effect_noise((1024, 1024), 80).convert("RGB").save(buf, "PNG")
    with pytest.raises(ValueError):
        save_jpeg(buf.getvalue(), tmp_path / "x.jpg", max_kb=5)
    # Verify no file was written
    assert not (tmp_path / "x.jpg").exists()


def test_skips_recipes_that_already_have_an_image(tmp_path):
    """Test that generate skips recipes with existing images."""
    calls = []

    class Stub:
        def invoke_model(self, **kw):
            calls.append(kw)
            raise AssertionError("should not be called")

    assert generate([dict(R, image="images/recipe-100.png")], Stub(), tmp_path) == ([], [])
    assert calls == []


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 40)).save(buf, "PNG")
    return buf.getvalue()


class RecStub:
    def __init__(self, fail_on=None):
        self.bodies = []
        self.fail_on = fail_on

    def invoke_model(self, modelId, body):
        b = json.loads(body)
        self.bodies.append(b)
        if self.fail_on and self.fail_on in b["textToImageParams"]["text"]:
            raise ClientError({"Error": {"Code": "Throttling", "Message": "secret body"}}, "InvokeModel")
        payload = json.dumps({"images": [base64.b64encode(_png()).decode()]}).encode()
        return {"body": io.BytesIO(payload)}


@pytest.mark.parametrize("line,expected", [
    ("1 large onion", "large onion"), ("2 garlic cloves", "garlic cloves"),
    ("1 litre stock", "stock"), ("1 lemon", "lemon"), ("200g red lentils", "red lentils"),
])
def test_main_ingredients_strip_quantity_and_unit(line, expected):
    assert _main_ingredients([line]) == [expected]


def test_seed_offset_applied(tmp_path):
    stub = RecStub()
    generate([R], stub, tmp_path / "stg", seed_offset=7, images_dir=tmp_path / "img")
    assert stub.bodies[0]["imageGenerationConfig"]["seed"] == 107


def test_writes_to_created_staging_dir(tmp_path):
    done, failed = generate([R], RecStub(), tmp_path / "a" / "stg", images_dir=tmp_path / "img")
    assert done == ["recipe-100"] and failed == [] and (tmp_path / "a" / "stg" / "recipe-100.jpg").exists()


def test_skips_existing_in_staging_or_images_unless_force(tmp_path):
    stg, img = tmp_path / "stg", tmp_path / "img"
    stg.mkdir(); img.mkdir()
    (stg / "recipe-100.jpg").write_bytes(b"x")
    r2 = dict(R, recipe_id="recipe-101")
    (img / "recipe-101.jpg").write_bytes(b"x")
    stub = RecStub()
    assert generate([R, r2], stub, stg, images_dir=img) == ([], [])
    assert stub.bodies == []
    done, _ = generate([R, r2], stub, stg, force=True, images_dir=img)
    assert done == ["recipe-100", "recipe-101"]


def test_one_failure_does_not_stop_run(tmp_path):
    bad = dict(R, recipe_id="recipe-101", title="Bad Dish")
    done, failed = generate([bad, R], RecStub(fail_on="Bad Dish"), tmp_path / "stg", images_dir=tmp_path / "img")
    assert done == ["recipe-100"] and failed == [("recipe-101", "ClientError")]


def test_contact_sheet_escapes_html_lists_all_staged_and_unchecked(tmp_path):
    stg = tmp_path / "stg"
    stg.mkdir()
    (stg / "recipe-100.jpg").write_bytes(b"x")
    (stg / "recipe-200.jpg").write_bytes(b"x")
    sheet = tmp_path / "sheet.html"
    write_contact_sheet([dict(R, title="<b>&")], stg, sheet)
    h = sheet.read_text()
    assert "&lt;b&gt;&amp;" in h and "<b>&" not in h.replace("<b>recipe", "")
    assert "recipe-200" in h and "checked" not in h.replace("input[data-id]:checked", "")
    assert "Approve" in h and "Download approved ids" in h and "approved_image_ids.json" in h


def test_invoke_request_and_decoding():
    stub = RecStub()
    out = _invoke(stub, "a prompt", seed=42)
    b = stub.bodies[0]
    assert b["taskType"] == "TEXT_IMAGE"
    assert b["imageGenerationConfig"]["width"] == 1024 and b["imageGenerationConfig"]["height"] == 1024
    assert b["imageGenerationConfig"]["seed"] == 42
    assert out == _png()
