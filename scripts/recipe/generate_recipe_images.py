"""Generate illustrative food photos for recipes without one (Amazon Nova Canvas)."""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
from pathlib import Path
from typing import List, Tuple

import boto3
from botocore.exceptions import ClientError
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
RECIPES = REPO_ROOT / "data" / "recipe" / "recipes_full.json"
IMG_DIR = REPO_ROOT / "data" / "recipe" / "images"
STAGING_DIR = REPO_ROOT / "data" / "recipe" / "images_staging"
MODEL_ID = "amazon.nova-canvas-v1:0"
NEGATIVE = "text, words, letters, logo, watermark, people, hands, faces, cutlery clutter, packaging"


def _main_ingredients(lines: List[str], n: int = 4) -> List[str]:
    out = []
    for line in lines[:n]:
        out.append(re.sub(r"^[\d½¼¾/.\s]*(?:(?:kg|g|ml|litres?|l|tbsp|tsp|cups?)\b\s*)?", "", line, flags=re.I).split(",")[0])
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


def generate(recipes: List[dict], client, out_dir: Path, only_missing: bool = True,
             seed_offset: int = 0, force: bool = False,
             images_dir: Path = IMG_DIR) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Generate images into out_dir (staging). Returns (done_ids, failed) where
    failed is a list of (recipe_id, error class name); one failure never stops the run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    done: List[str] = []
    failed: List[Tuple[str, str]] = []
    for r in recipes:
        rid = r["recipe_id"]
        if only_missing and r.get("image"):
            continue
        out = out_dir / f"{rid}.jpg"
        if not force and (out.exists() or (images_dir / f"{rid}.jpg").exists()):
            continue
        try:
            num = int(rid.split("-")[1])
            save_jpeg(_invoke(client, build_prompt(r), seed=num + seed_offset), out)
        except (ClientError, ValueError, KeyError) as exc:
            failed.append((rid, type(exc).__name__))
            continue
        done.append(rid)
    return done, failed


_SHEET_JS = (
    "function dl(){var ids=[].slice.call(document.querySelectorAll('input[data-id]:checked'))"
    ".map(function(e){return e.getAttribute('data-id')});"
    "var a=document.createElement('a');"
    "a.href=URL.createObjectURL(new Blob([JSON.stringify(ids)],{type:'application/json'}));"
    "a.download='approved_image_ids.json';a.click()}"
)


def write_contact_sheet(recipes: List[dict], staging_dir: Path, path: Path) -> None:
    """Contact sheet of every .jpg in staging; nothing is approved by default."""
    by_id = {r["recipe_id"]: r for r in recipes}
    cells = ""
    for jpg in sorted(staging_dir.glob("*.jpg")):
        i = jpg.stem
        r = by_id.get(i, {})
        e = html.escape
        cells += (
            f"<figure><img src='{e(i, quote=True)}.jpg' loading='lazy'>"
            f"<figcaption><b>{e(i)}</b> {e(str(r.get('title', '')))}<br>"
            f"<small>{e('; '.join(r.get('ingredients') or [])[:200])}</small><br>"
            f"<label><input type=checkbox data-id='{e(i, quote=True)}'> Approve</label></figcaption></figure>"
        )
    path.write_text(
        "<!doctype html><meta charset=utf-8><title>Recipe images</title><style>"
        "body{font:14px system-ui;margin:16px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}"
        "img{width:100%;border-radius:8px}</style>"
        "<button onclick='dl()'>Download approved ids</button><main>" + cells + "</main>"
        "<script>" + _SHEET_JS + "</script>"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="regenerate even if an image file exists")
    args = ap.parse_args()
    recipes = json.loads(RECIPES.read_text())["recipes"]
    if args.ids:
        wanted = set(args.ids.split(","))
        recipes = [r for r in recipes if r["recipe_id"] in wanted]
    if args.limit:
        recipes = [r for r in recipes if not r.get("image")][: args.limit]
    client = boto3.client("bedrock-runtime", region_name=args.region)
    ids, failed = generate(recipes, client, STAGING_DIR, seed_offset=args.seed_offset, force=args.force)
    write_contact_sheet(json.loads(RECIPES.read_text())["recipes"], STAGING_DIR, STAGING_DIR / "contact_sheet.html")
    print(f"generated={len(ids)} failed={len(failed)}")
    for rid, err in failed:
        print(f"failed {rid}: {err}")


if __name__ == "__main__":
    main()
