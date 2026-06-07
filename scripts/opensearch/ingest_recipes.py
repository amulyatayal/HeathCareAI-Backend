"""
Ingest parsed recipes (data/recipe/recipes_full.json) into OpenSearch.

Creates/uses a dedicated index named after KnowledgeBase.RECIPE ("recipe_catalog")
so the existing MEAL_PLANNING routing points at it with no further wiring. Unlike
the generic KnowledgeBaseService.add_document path (which only keeps title/content
+ a few keyword fields), this stores the FULL structured recipe so the RecipeAgent
can filter by diet/allergen/stage and render nutrition cards — while still keeping
`title`/`content`/`embedding` for compatibility with the generic hybrid retriever.

Embeddings reuse EmbeddingService (Bedrock Titan v2, 1024-dim).

Usage:
    python scripts/opensearch/ingest_recipes.py --dry-run
    python scripts/opensearch/ingest_recipes.py --recreate            # full load
    python scripts/opensearch/ingest_recipes.py --limit 5             # smoke test
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv()

from config.aws import opensearch
from config.settings import settings
from config.agent_routing import KnowledgeBase
from services.knowledge_base import EmbeddingService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = REPO_ROOT / "data" / "recipe" / "recipes_full.json"
DEFAULT_INDEX = KnowledgeBase.RECIPE.value  # "recipe_catalog"


def recipe_index_mapping() -> dict:
    """Hybrid (BM25 + kNN) mapping that keeps recipe structure queryable."""
    return {
        "settings": {
            "index": {
                "number_of_shards": 2,
                "number_of_replicas": 1,
                "knn": True,
            }
        },
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "recipe_number": {"type": "integer"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "content": {"type": "text", "analyzer": "standard"},  # searchable blob
                "emoji": {"type": "keyword"},
                "meal_type": {"type": "keyword"},
                "cuisine_type": {"type": "keyword"},
                "category": {"type": "keyword"},
                "category_label": {"type": "keyword"},
                "dietary_tags": {"type": "keyword"},      # filterable
                "allergens": {"type": "keyword"},         # filter/exclude
                "allergen_info": {"type": "text"},
                "symptom_support": {"type": "keyword"},
                "texture_class": {"type": "keyword"},
                "stages": {"type": "keyword"},
                "stage_display_names": {"type": "keyword"},
                "description": {"type": "text"},
                "clinical_notes": {"type": "text"},
                "ingredients": {"type": "text"},
                "instructions": {"type": "text"},
                "tips": {"type": "text"},
                "has_full_recipe": {"type": "boolean"},
                "servings": {"type": "integer"},
                "prep_time_mins": {"type": "integer"},
                "cook_time_mins": {"type": "integer"},
                "calories": {"type": "integer"},
                "nutrition": {"type": "object", "enabled": True},
                "nutrition_detail": {"type": "object", "enabled": True},
                "source_title": {"type": "text"},
                "source_url": {"type": "keyword"},
                "source_page": {"type": "integer"},
                "image": {"type": "keyword"},
                "created_at": {"type": "date"},
                "data_source": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": settings.kb_embedding_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "faiss",
                        "parameters": {"ef_construction": 512, "m": 16},
                    },
                },
            }
        },
    }


def build_searchable_text(r: dict) -> str:
    """Compose the text used for both BM25 `content` and the embedding."""
    parts = [
        r.get("title", ""),
        f"Category: {r.get('category_label', '')}.",
        f"Diet: {', '.join(r.get('dietary_tags', []))}.",
        f"Suitable for breast cancer stages: {', '.join(r.get('stages', []))}.",
        f"Symptom support: {', '.join(r.get('symptom_support', []))}.",
        r.get("description", "") or r.get("clinical_notes", ""),
    ]
    if r.get("ingredients"):
        parts.append("Ingredients: " + "; ".join(r["ingredients"]) + ".")
    return " ".join(p for p in parts if p and p.strip())


def to_doc(r: dict, embedding: List[float]) -> dict:
    src = r.get("source") or {}
    nutrition = r.get("nutrition") or {}
    return {
        "document_id": r["recipe_id"],
        "recipe_number": r.get("recipe_number"),
        "title": r.get("title", ""),
        "content": build_searchable_text(r),
        "emoji": r.get("emoji", ""),
        "meal_type": r.get("meal_type"),
        "cuisine_type": r.get("cuisine_type"),
        "category": r.get("category"),
        "category_label": r.get("category_label"),
        "dietary_tags": r.get("dietary_tags", []),
        "allergens": r.get("allergens", []),
        "allergen_info": r.get("allergen_info", ""),
        "symptom_support": r.get("symptom_support", []),
        "texture_class": r.get("texture_class"),
        "stages": r.get("stages", []),
        "stage_display_names": r.get("stage_display_names", []),
        "description": r.get("description", ""),
        "clinical_notes": r.get("clinical_notes", ""),
        "ingredients": r.get("ingredients", []),
        "instructions": r.get("instructions", []),
        "tips": r.get("tips"),
        "has_full_recipe": r.get("has_full_recipe", False),
        "servings": r.get("servings"),
        "prep_time_mins": r.get("prep_time_mins"),
        "cook_time_mins": r.get("cook_time_mins"),
        "calories": nutrition.get("calories_per_serving") or 0,
        "nutrition": nutrition,
        "nutrition_detail": r.get("nutrition_detail", {}),
        "source_title": src.get("title", ""),
        "source_url": src.get("url", ""),
        "source_page": src.get("page"),
        "image": r.get("image"),
        "created_at": r.get("created_at") or datetime.utcnow().isoformat(),
        "data_source": r.get("data_source", ""),
        "embedding": embedding,
    }


def ensure_index(client, index_name: str, recreate: bool) -> None:
    exists = client.indices.exists(index=index_name)
    if exists and recreate:
        logger.info("Deleting existing index %s (--recreate)", index_name)
        client.indices.delete(index=index_name)
        exists = False
    if not exists:
        client.indices.create(index=index_name, body=recipe_index_mapping())
        logger.info("Created index: %s", index_name)
    else:
        logger.info("Index already exists: %s", index_name)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest recipes into OpenSearch")
    ap.add_argument("--file", default=str(DATA_FILE), help="recipes_full.json path")
    ap.add_argument("--index", default=DEFAULT_INDEX, help="target index name")
    ap.add_argument("--limit", type=int, default=0, help="ingest only first N (0=all)")
    ap.add_argument("--recreate", action="store_true", help="drop + recreate the index")
    ap.add_argument("--dry-run", action="store_true", help="parse + embed nothing, no writes")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"Not found: {path} — run scripts/recipe/parse_recipes.py first")

    data = json.loads(path.read_text(encoding="utf-8"))
    recipes = data.get("recipes", [])
    if args.limit:
        recipes = recipes[: args.limit]

    logger.info("=" * 60)
    logger.info("RECIPE INGESTION -> OpenSearch")
    logger.info("  index:   %s", args.index)
    logger.info("  recipes: %d", len(recipes))
    logger.info("  dry-run: %s | recreate: %s", args.dry_run, args.recreate)
    logger.info("=" * 60)

    if args.dry_run:
        for r in recipes[:3]:
            logger.info("[DRY] %s | %s | dietary_tags=%s allergens=%s full=%s",
                        r["recipe_id"], r["title"], r.get("dietary_tags"),
                        r.get("allergens"), r.get("has_full_recipe"))
            logger.info("      search_text: %s", build_searchable_text(r)[:160])
        logger.info("[DRY] would ingest %d recipes (no writes).", len(recipes))
        return

    client = opensearch()
    embedder = EmbeddingService()
    ensure_index(client, args.index, args.recreate)

    ok = err = 0
    start = time.time()
    for i, r in enumerate(recipes, 1):
        try:
            emb = embedder.create_embedding(build_searchable_text(r))
            if not emb:
                logger.warning("  no embedding for %s — skipped", r["id"])
                err += 1
                continue
            client.index(index=args.index, body=to_doc(r, emb))
            ok += 1
            if i % 25 == 0:
                logger.info("  progress: %d/%d", i, len(recipes))
        except Exception as exc:  # noqa: BLE001
            logger.error("  error on %s: %s", r.get("id"), exc)
            err += 1

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info("DONE  indexed=%d  errors=%d  time=%.1fs (%.2fs/doc)",
                ok, err, elapsed, elapsed / max(ok, 1))
    logger.info("  index: %s", args.index)


if __name__ == "__main__":
    main()
