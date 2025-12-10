"""
Script to ingest Q&A data into the Knowledge Base
Parses the SampleQ&A file and uploads to OpenSearch
"""

import sys
import re
import asyncio
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from services.knowledge_base import get_knowledge_base, create_index_if_not_exists
from models.schemas import KnowledgeDocument, QueryCategory, ContentType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_qa_file(file_path: str) -> list[dict]:
    """
    Parse the Q&A file into structured documents.
    
    Expected format:
    1. Question text?
    
    Answer paragraph...
    
    2. Next question?
    ...
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by question pattern (number followed by period and space)
    pattern = r'(\d+)\.\s+(.+?)(?=\n\n|\Z)'
    
    documents = []
    
    # Find all Q&A pairs
    lines = content.strip().split('\n')
    current_question = None
    current_answer = []
    current_num = None
    
    for line in lines:
        # Check if this is a new question (starts with number followed by period)
        match = re.match(r'^(\d+)\.\s+(.+)$', line)
        if match:
            # Save previous Q&A if exists
            if current_question and current_answer:
                documents.append({
                    'number': current_num,
                    'question': current_question,
                    'answer': ' '.join(current_answer).strip()
                })
            
            current_num = int(match.group(1))
            current_question = match.group(2)
            current_answer = []
        elif line.strip():  # Non-empty line is part of answer
            current_answer.append(line.strip())
    
    # Don't forget the last Q&A
    if current_question and current_answer:
        documents.append({
            'number': current_num,
            'question': current_question,
            'answer': ' '.join(current_answer).strip()
        })
    
    return documents


def categorize_question(question: str) -> QueryCategory:
    """Categorize a question based on keywords"""
    q_lower = question.lower()
    
    # Define keyword mappings
    categories = {
        QueryCategory.SYMPTOMS: ['symptom', 'lump', 'pain', 'sign', 'feel', 'notice'],
        QueryCategory.TREATMENT: ['treatment', 'surgery', 'mastectomy', 'lumpectomy', 'chemo', 'radiation', 'therapy'],
        QueryCategory.MEDICATION: ['drug', 'medicine', 'tamoxifen', 'aromatase', 'hormone tablet', 'HER2'],
        QueryCategory.SIDE_EFFECTS: ['side effect', 'nausea', 'fatigue', 'hair', 'vomit', 'tired'],
        QueryCategory.LIFESTYLE: ['exercise', 'work', 'travel', 'diet', 'alcohol', 'yoga'],
        QueryCategory.EMOTIONAL_SUPPORT: ['anxious', 'scared', 'fear', 'cope', 'support', 'emotion', 'partner', 'sex', 'intimacy'],
        QueryCategory.NUTRITION: ['diet', 'food', 'eat', 'supplement', 'vitamin', 'sugar'],
        QueryCategory.FOLLOW_UP_CARE: ['follow-up', 'check-up', 'scan', 'recurrence', 'come back', 'survivor']
    }
    
    for category, keywords in categories.items():
        if any(kw in q_lower for kw in keywords):
            return category
    
    return QueryCategory.GENERAL


async def ingest_documents(documents: list[dict], dry_run: bool = False):
    """Ingest documents into the knowledge base"""
    
    if not dry_run:
        # Create index if it doesn't exist
        logger.info("Checking/creating OpenSearch index...")
        if not create_index_if_not_exists():
            logger.error("Failed to create index. Check OpenSearch configuration.")
            return
    
    kb = get_knowledge_base()
    
    success_count = 0
    error_count = 0
    
    for doc in documents:
        try:
            # Create knowledge document
            category = categorize_question(doc['question'])
            
            knowledge_doc = KnowledgeDocument(
                id=f"qa_{doc['number']:03d}",
                title=doc['question'],
                content=f"Question: {doc['question']}\n\nAnswer: {doc['answer']}",
                content_type=ContentType.FAQ,
                category=category,
                tags=["breast-cancer", "patient-faq", f"q{doc['number']}"],
                author="Healthcare AI Team"
            )
            
            if dry_run:
                logger.info(f"[DRY RUN] Would add: Q{doc['number']}: {doc['question'][:50]}... | Category: {category.value}")
            else:
                doc_id = await kb.add_document(knowledge_doc)
                logger.info(f"Added Q{doc['number']}: {doc['question'][:50]}... -> {doc_id}")
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Error adding Q{doc['number']}: {e}")
            error_count += 1
    
    logger.info(f"\n{'='*50}")
    logger.info(f"Ingestion complete!")
    logger.info(f"  Successful: {success_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info(f"  Total: {len(documents)}")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Ingest Q&A data into Knowledge Base')
    parser.add_argument('--file', '-f', 
                        default='data/sample/SampleQ&A-1',
                        help='Path to Q&A file')
    parser.add_argument('--dry-run', '-d', 
                        action='store_true',
                        help='Parse and show what would be uploaded without actually uploading')
    
    args = parser.parse_args()
    
    # Get absolute path
    script_dir = Path(__file__).parent.parent
    file_path = script_dir / args.file
    
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return
    
    logger.info(f"Parsing Q&A file: {file_path}")
    documents = parse_qa_file(str(file_path))
    logger.info(f"Found {len(documents)} Q&A pairs")
    
    if args.dry_run:
        logger.info("\n[DRY RUN MODE - No data will be uploaded]\n")
    
    await ingest_documents(documents, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())

