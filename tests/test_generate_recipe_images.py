"""Tests for recipe image generation script."""
import io
from pathlib import Path

import pytest
from PIL import Image

from scripts.recipe.generate_recipe_images import build_prompt, save_jpeg, generate


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

    assert generate([dict(R, image="images/recipe-100.png")], Stub(), tmp_path) == []
    assert calls == []
