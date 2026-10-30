"""Generate illustrative food photos for recipes without one (Amazon Nova Canvas)."""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path
from typing import List

import boto3
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
RECIPES = REPO_ROOT / "data" / "recipe" / "recipes_full.json"
IMG_DIR = REPO_ROOT / "data" / "recipe" / "images"
MODEL_ID = "amazon.nova-canvas-v1:0"
NEGATIVE = "text, words, letters, logo, watermark, people, hands, faces, cutlery clutter, packaging"


def _main_ingredients(lines: List[str], n: int = 4) -> List[str]:
    out = []
    for line in lines[:n]:
        out.append(re.sub(r"^[\d½¼¾/.\s]*(g|kg|ml|l|litre|tbsp|tsp|cups?)?\s*", "", line, flags=re.I).split(",")[0])
    return out


def build_prompt(recipe: dict) -> str:
    ing = ", ".join(_main_ingredients(recipe.get("ingredients") or []))
    return (
        f"Overhead food photograph of {recipe['title']}, a home-cooked {recipe.get('meal_type', 'dish')}"
        + (f" made with {ing}" if ing else "")
        + ". Served on a plain ceramic plate or bowl, natural daylight, simple neutral background,"
        " realistic, appetising, no text, no people."
    )


def save_jpeg(png_bytes: bytes, out: Path, max_kb: int = 300) -> int:
    """Convert PNG bytes to JPEG and save under size limit.

    Args:
        png_bytes: PNG image data
        out: Output path for JPEG
        max_kb: Maximum file size in KB

    Returns:
        Number of bytes written

    Raises:
        ValueError: If image cannot fit in max_kb even at lowest quality (20)
    """
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize((1024, 1024))
    quality_ladder = (88, 80, 72, 64, 56, 48, 40, 32, 24, 20)
    buf = None

    for quality in quality_ladder:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() <= max_kb * 1024:
            break

    # If we've gone through the entire ladder and still too large, raise error
    if buf.tell() > max_kb * 1024:
        raise ValueError(
            f"Image cannot fit in {max_kb} KB even at lowest quality (20). "
            f"Current size: {buf.tell() / 1024:.1f} KB"
        )

    out.write_bytes(buf.getvalue())
    return buf.tell()


def _invoke(client, prompt: str, seed: int) -> bytes:
    body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt, "negativeText": NEGATIVE},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "width": 1024,
            "height": 1024,
            "quality": "standard",
            "cfgScale": 7.0,
            "seed": seed,
        },
    }
    resp = client.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
    return base64.b64decode(json.loads(resp["body"].read())["images"][0])


def generate(recipes: List[dict], client, out_dir: Path, only_missing: bool = True) -> List[str]:
    done = []
    for r in recipes:
        if only_missing and r.get("image"):
            continue
        num = int(r["recipe_id"].split("-")[1])
        out = out_dir / f"{r['recipe_id']}.jpg"
        save_jpeg(_invoke(client, build_prompt(r), seed=num), out)
        done.append(r["recipe_id"])
    return done


def write_contact_sheet(recipes: List[dict], ids: List[str], path: Path) -> None:
    cells = "".join(
        f"<figure><img src='../images/{i}.jpg' loading='lazy'><figcaption><b>{i}</b> {r['title']}<br>"
        f"<small>{'; '.join(r.get('ingredients') or [])[:200]}</small><br>"
        f"<label><input type=checkbox data-id='{i}'> Looks wrong</label></figcaption></figure>"
        for r in recipes
        for i in [r["recipe_id"]]
        if i in ids
    )
    path.write_text(
        "<!doctype html><meta charset=utf-8><title>Recipe images</title><style>"
        "body{font:14px system-ui;margin:16px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}"
        "img{width:100%;border-radius:8px}</style><main>" + cells + "</main>"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()
    recipes = json.loads(RECIPES.read_text())["recipes"]
    if args.ids:
        wanted = set(args.ids.split(","))
        recipes = [r for r in recipes if r["recipe_id"] in wanted]
    if args.limit:
        recipes = [r for r in recipes if not r.get("image")][: args.limit]
    client = boto3.client("bedrock-runtime", region_name=args.region)
    ids = generate(recipes, client, IMG_DIR)
    write_contact_sheet(
        recipes, ids, REPO_ROOT / "data" / "recipe" / "review" / "image_contact_sheet.html"
    )
    print(f"generated={len(ids)}")


if __name__ == "__main__":
    main()
