"""
Ingest ProcessedQ&A CSV into OpenSearch with embeddings
"""

import sys
import csv
import asyncio
import logging
import time
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from services.knowledge_base import get_knowledge_base, create_index_if_not_exists
from models.schemas import KnowledgeDocument, ContentType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Map CSV categories to a normalized set
CATEGORY_MAPPING = {
    "SYMPTOMS": "symptoms",
    "SURGERY_PROCEDURES": "treatment",
    "DRAINS_WOUND_CARE": "treatment",
    "DRAIN_WOUND_CARE": "treatment",
    "CANCER_TREATMENT": "treatment",
    "MEDICATION": "medication",
    "SIDE_EFFECTS": "side_effects",
    "PRE_SURGERY_PREHAB": "treatment",
    "POST_SURGERY_RECOVERY": "follow_up_care",
    "FOLLOW_UP_CARE": "follow_up_care",
    "LIFESTYLE": "lifestyle",
    "NUTRITION": "nutrition",
    "EMOTIONAL_SUPPORT": "emotional_support",
    "DIAGNOSIS_TESTING": "symptoms",
    "ADMIN_LOGISTICS": "general",
    "SAFETY_RED_FLAGS": "symptoms",
    "FERTILITY": "lifestyle",
    "PREGNANCY_DECISION": "lifestyle",
    "PREGNANCY_IMPACT": "lifestyle",
    "BREASTFEEDING": "lifestyle",
    "CANCER_RISK": "general",
    "CAUSES": "general",
    "PREVENTION": "general",
    "RISK_FACTORS": "general",
    "MYTHS_AND_FACTS": "general",
    "MYTHS_MISCONCEPTIONS": "general",
    "GENETIC_TESTING": "symptoms",
    "CLINICAL_TRIALS": "general",
    "RESEARCH": "general",
    "PROGNOSIS": "general",
    "TREATMENT": "treatment",
    "TREATMENT_DECISION": "treatment",
    "DECISION_MAKING": "treatment",
    "DECISION_ABOUT_TREATMENT": "treatment",
    "TREATMENT_PLANNING": "treatment",
    "TREATMENT_DURATION": "treatment",
    "ALTERNATIVE_THERAPIES": "treatment",
    "HAIR_CARE": "side_effects",
    "HAIR_LOSS_MANAGEMENT": "side_effects",
    "PREVENTING_HAIR_LOSS": "side_effects",
    "SEX_AND_INTIMACY": "emotional_support",
    "FAMILY_AND_FRIENDS": "emotional_support",
    "PRACTICAL_SUPPORT": "emotional_support",
    "SUPPORT_SERVICES": "emotional_support",
    "FINANCIAL_SUPPORT": "general",
    "FINANCIAL_ASSISTANCE": "general",
    "PHYSICAL_ACTIVITY": "lifestyle",
    "VACCINATIONS": "general",
    "AWARENESS": "general"
}


def read_csv_file(csv_path: Path) -> list:
    """Read CSV and parse Q&A pairs"""
    qa_pairs = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        # Use tab delimiter as shown in the file
        reader = csv.DictReader(f, delimiter='\t')
        
        for row in reader:
            try:
                # Skip if question or answer is empty
                if not row.get('Question (100 words)') or not row.get('Answer (Max 2000 words)'):
                    continue
                
                qa_pairs.append({
                    'sno': row.get('Sno.', ''),
                    'question': row['Question (100 words)'].strip(),
                    'answer': row['Answer (Max 2000 words)'].strip(),
                    'category': row.get('Question Category (Refer Sheet 2)', 'GENERAL').strip(),
                    'source': row.get('Source of Data (Preferable URL)', '').strip(),
                    'excerpt': row.get('Actual Excerpt from the Source Data', '').strip(),
                    'date': row.get('Date', ''),
                    'author': row.get('Author Name', 'Healthcare AI Team')
                })
            except Exception as e:
                logger.warning(f"Error parsing row: {e}")
                continue
    
    return qa_pairs


def normalize_category(csv_category: str) -> str:
    """Map CSV category to schema category"""
    return CATEGORY_MAPPING.get(csv_category.upper(), "general")


async def ingest_qa_pairs(qa_pairs: list, dry_run: bool = False, index_name: str = None):
    """Ingest Q&A pairs into knowledge base with embeddings"""
    
    if not dry_run:
        logger.info(f"Checking/creating OpenSearch index with vector support...")
        if index_name:
            logger.info(f"Target index: {index_name}")
        if not create_index_if_not_exists(use_vectors=True, index_name=index_name):
            logger.error("Failed to create index")
            return
    
    # Initialize knowledge base with vectors
    kb = get_knowledge_base(use_vectors=True, index_name=index_name)
    
    success_count = 0
    error_count = 0
    skipped_count = 0
    start_time = time.time()
    
    logger.info(f"\nStarting ingestion of {len(qa_pairs)} Q&A pairs with embeddings...")
    logger.info(f"Dry run: {dry_run}\n")
    
    for i, qa in enumerate(qa_pairs):
        try:
            # Map category
            category = normalize_category(qa['category'])
            
            # Create document
            document = KnowledgeDocument(
                id=f"csv_qa_{qa['sno']}",
                title=qa['question'],
                content=f"Question: {qa['question']}\n\nAnswer: {qa['answer']}",
                content_type=ContentType.FAQ,
                category=category,
                source_url=qa['source'] if qa['source'] else None,
                author=qa['author'],
                tags=["breast-cancer", "patient-faq", qa['category'].lower()],
                metadata={
                    "original_category": qa['category'],
                    "excerpt": qa['excerpt'][:500] if qa['excerpt'] else "",
                    "date_added": qa['date']
                }
            )
            
            if dry_run:
                logger.info(f"[DRY RUN] Would add Q{qa['sno']}: {qa['question'][:50]}... | Category: {category}")
                success_count += 1
            else:
                doc_id = await kb.add_document(document)
                
                if (i + 1) % 50 == 0:
                    logger.info(f"Progress: {i+1}/{len(qa_pairs)} ({(i+1)/len(qa_pairs)*100:.1f}%)")
                
                success_count += 1
                
        except Exception as e:
            logger.error(f"Error adding Q{qa.get('sno', '?')}: {e}")
            error_count += 1
    
    elapsed = time.time() - start_time
    
    logger.info(f"\n{'='*60}")
    logger.info(f"INGESTION COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  Successful: {success_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info(f"  Skipped: {skipped_count}")
    logger.info(f"  Total: {len(qa_pairs)}")
    logger.info(f"  Time: {elapsed:.1f}s ({elapsed/len(qa_pairs):.2f}s per doc)")
    logger.info(f"  Vectors: Enabled (Hybrid Search)")
    
    # Category distribution
    category_counts = {}
    for qa in qa_pairs:
        cat = normalize_category(qa['category'])
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    logger.info(f"\n  Category distribution after mapping:")
    for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"    - {cat}: {count}")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Ingest CSV Q&A into Knowledge Base')
    parser.add_argument('--file', '-f',
                        default='data/ProcessedQ&A_Generated.csv',
                        help='Path to CSV file')
    parser.add_argument('--index', '-i',
                        default=None,
                        help='OpenSearch index name (default: from config)')
    parser.add_argument('--dry-run', '-d',
                        action='store_true',
                        help='Parse and show what would be uploaded')
    
    args = parser.parse_args()
    
    # Get absolute path
    script_dir = Path(__file__).parent.parent
    file_path = script_dir / args.file
    
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return
    
    logger.info("="*60)
    logger.info("CSV TO OPENSEARCH INGESTION")
    logger.info("="*60)
    logger.info(f"Input file: {file_path}")
    logger.info(f"Target index: {args.index or 'default from config'}")
    logger.info(f"Using hybrid search (vector + keyword)")
    logger.info("="*60 + "\n")
    
    # Read CSV
    logger.info(f"Reading CSV file...")
    qa_pairs = read_csv_file(file_path)
    logger.info(f"Found {len(qa_pairs)} Q&A pairs\n")
    
    if not qa_pairs:
        logger.error("No Q&A pairs found in CSV!")
        return
    
    # Show sample
    logger.info("Sample Q&A:")
    for i, qa in enumerate(qa_pairs[:3]):
        logger.info(f"  Q{qa['sno']}: {qa['question'][:60]}...")
        logger.info(f"       Category: {qa['category']} -> {normalize_category(qa['category'])}")
        logger.info(f"       Source: {qa['source'][:50] if qa['source'] else 'N/A'}")
        logger.info("")
    
    # Ingest
    await ingest_qa_pairs(qa_pairs, dry_run=args.dry_run, index_name=args.index)


if __name__ == "__main__":
    asyncio.run(main())

