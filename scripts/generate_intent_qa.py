"""
Generate Q&A pairs for per-intent knowledge bases.
Creates TWO answer variants per question:
  1. Generated: AI-written answer using leaflet content
  2. Citation-only: Verbatim excerpt from PDF (no paraphrasing)

Usage:
  # Generate Q&A for a single intent (for testing)
  python scripts/generate_intent_qa.py --intent medication_info
  
  # Generate Q&A for all intents
  python scripts/generate_intent_qa.py --all
  
  # Dry run (no indexing)
  python scripts/generate_intent_qa.py --intent medication_info --dry-run
"""

import sys
import json
import asyncio
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# PDF processing
try:
    import PyPDF2
except ImportError:
    print("Installing PyPDF2...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2"])
    import PyPDF2

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from config import bedrock
from config.pipeline_config import IntentCategory

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


# ================================
# Configuration
# ================================

DATA_DIR = Path(__file__).parent.parent / "data" / "sample" / "raw" / "Leaflets"
MAPPING_FILE = Path(__file__).parent.parent / "config" / "intent_leaflets_mapping.json"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "intent_qa"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_intent_mapping() -> Dict:
    """Load the intent-to-leaflets mapping configuration."""
    with open(MAPPING_FILE, 'r') as f:
        mapping = json.load(f)
    # Remove metadata keys
    return {k: v for k, v in mapping.items() if not k.startswith('_')}


def extract_text_with_pages(pdf_path: Path) -> List[Dict]:
    """Extract text from PDF with page number tracking."""
    try:
        logger.info(f"  Extracting text from: {pdf_path.name}")
        
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            pages = []
            
            for page_num, page in enumerate(pdf_reader.pages, 1):
                text = page.extract_text()
                if text and text.strip():
                    pages.append({
                        "page_num": page_num,
                        "text": text.strip(),
                        "source_file": pdf_path.name
                    })
            
            logger.info(f"    Extracted {len(pages)} pages")
            return pages
            
    except Exception as e:
        logger.error(f"  Error extracting text from {pdf_path.name}: {e}")
        return []


def chunk_pages(pages: List[Dict], max_chunk_size: int = 5000) -> List[Dict]:
    """Combine pages into chunks while tracking page ranges."""
    chunks = []
    current_text = []
    current_start = None
    current_end = None
    current_size = 0
    source_file = pages[0]["source_file"] if pages else ""
    
    for page in pages:
        page_size = len(page["text"])
        
        if current_size + page_size > max_chunk_size and current_text:
            chunks.append({
                "text": "\n\n".join(current_text),
                "page_start": current_start,
                "page_end": current_end,
                "source_file": source_file
            })
            current_text = [page["text"]]
            current_start = page["page_num"]
            current_end = page["page_num"]
            current_size = page_size
        else:
            current_text.append(page["text"])
            if current_start is None:
                current_start = page["page_num"]
            current_end = page["page_num"]
            current_size += page_size
    
    if current_text:
        chunks.append({
            "text": "\n\n".join(current_text),
            "page_start": current_start,
            "page_end": current_end,
            "source_file": source_file
        })
    
    return chunks


async def generate_dual_qa_pairs(
    chunk: Dict,
    intent: str,
    max_questions: int = 0  # 0 = no limit
) -> List[Dict]:
    """
    Generate Q&A pairs in BOTH modes:
      1. Generated: AI-written answer
      2. Citation-only: Verbatim excerpt
    
    Returns list of Q&A documents ready for indexing.
    """
    try:
        client = bedrock()
        
        question_instruction = f"Create up to {max_questions} question-answer pairs" if max_questions > 0 else "Create ALL relevant question-answer pairs"
        
        prompt = f"""You are a medical content specialist creating educational Q&A pairs from a breast cancer patient information leaflet.

TASK: {question_instruction} from the following document section.
Extract every distinct piece of patient-relevant information as a separate Q&A.
For EACH question, you must provide TWO answer types:

1. **generated_answer**: A comprehensive, empathetic answer that explains the information clearly to patients. Use natural language, be supportive, and synthesize information from the source.

2. **citation_answer**: The EXACT verbatim text from the document that answers the question. Copy word-for-word without any changes or paraphrasing. This must be a direct quote.

INTENT CATEGORY: {intent}
This Q&A should be relevant to questions about: {intent.replace('_', ' ')}

SOURCE DOCUMENT: {chunk['source_file']}
PAGES: {chunk['page_start']}-{chunk['page_end']}

DOCUMENT TEXT:
{chunk['text'][:12000]}

OUTPUT FORMAT (JSON array):
[
  {{
    "question": "Natural patient question here (max 100 words)",
    "generated_answer": "Comprehensive, empathetic AI-written answer (max 500 words)",
    "citation_answer": "Exact verbatim quote from the document that answers this question",
    "section": "Section or topic name if identifiable",
    "relevance_score": 0.9
  }}
]

CRITICAL RULES:
1. citation_answer MUST be a direct, unmodified quote from the document
2. generated_answer should be patient-friendly and supportive
3. Both answers must address the same question
4. Only create Q&A for information actually present in the document
5. relevance_score: 0.9+ for highly relevant, 0.7-0.9 for relevant, <0.7 for tangential

Generate the Q&A pairs now:"""

        # Use Claude Sonnet for higher quality Q&A generation
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "temperature": 0.0,  # Factual, deterministic
            "messages": [
                {"role": "user", "content": prompt}
            ]
        })
        
        response = client.invoke_model(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",
            body=body
        )
        
        response_body = json.loads(response['body'].read())
        ai_response = response_body['content'][0]['text']
        
        # Extract JSON
        json_match = re.search(r'\[[\s\S]*\]', ai_response)
        if not json_match:
            logger.warning("    Could not parse JSON from AI response")
            return []
        
        # Clean control characters that can break JSON parsing
        json_str = json_match.group(0)
        json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)  # Remove control chars
        json_str = json_str.replace('\n', ' ').replace('\r', ' ')  # Normalize newlines in values
        
        try:
            qa_pairs = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"    JSON parse error: {e}. Attempting repair...")
            # Try to fix common issues
            json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas
            json_str = re.sub(r',\s*}', '}', json_str)
            qa_pairs = json.loads(json_str)
        
        # Create documents for BOTH answer types
        documents = []
        for qa in qa_pairs:
            # The citation_answer is the source excerpt for both types
            source_excerpt = qa.get("citation_answer", "")
            
            base_doc = {
                "question": qa.get("question", ""),
                "source_file": chunk["source_file"],
                "section": qa.get("section", ""),
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "intent": intent,
                "created_at": datetime.utcnow().isoformat(),
                "relevance_score": qa.get("relevance_score", 0.8),
                "source_excerpt": source_excerpt  # Always include the verbatim source
            }
            
            # Document 1: Generated answer (with source reference)
            gen_doc = base_doc.copy()
            gen_doc["answer"] = qa.get("generated_answer", "")
            gen_doc["answer_type"] = "generated"
            documents.append(gen_doc)
            
            # Document 2: Citation-only answer (answer = source_excerpt)
            cite_doc = base_doc.copy()
            cite_doc["answer"] = source_excerpt
            cite_doc["answer_type"] = "citation_only"
            documents.append(cite_doc)
        
        logger.info(f"    Generated {len(qa_pairs)} Q&A pairs ({len(documents)} docs with both answer types)")
        return documents
        
    except Exception as e:
        logger.error(f"    Error generating Q&A: {e}")
        return []


async def process_intent(
    intent: str,
    mapping: Dict,
    dry_run: bool = False,
    max_questions_per_chunk: int = 0,
    single_leaflet: str = None,
    chunk_size: int = 5000
) -> Tuple[int, List[Dict]]:
    """Process all leaflets for a single intent and generate Q&A pairs."""
    
    intent_config = mapping.get(intent)
    if not intent_config:
        logger.error(f"Intent '{intent}' not found in mapping")
        return 0, []
    
    leaflets = intent_config.get("leaflets", [])
    
    # Filter to single leaflet if specified
    if single_leaflet:
        if single_leaflet in leaflets:
            leaflets = [single_leaflet]
            logger.info(f"Filtering to single leaflet: {single_leaflet}")
        else:
            logger.error(f"Leaflet '{single_leaflet}' not in intent '{intent}' mapping")
            logger.info(f"Available: {leaflets}")
            return 0, []
    kb_index = intent_config.get("kb_index", f"kb_{intent}")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing intent: {intent}")
    logger.info(f"KB index: {kb_index}")
    logger.info(f"Leaflets: {len(leaflets)}")
    logger.info(f"{'='*60}")
    
    if not leaflets:
        logger.warning(f"  No leaflets configured for intent: {intent}")
        return 0, []
    
    all_documents = []
    
    for leaflet_name in leaflets:
        pdf_path = DATA_DIR / leaflet_name
        
        if not pdf_path.exists():
            logger.warning(f"  Leaflet not found: {leaflet_name}")
            continue
        
        logger.info(f"\n  Processing: {leaflet_name}")
        
        # Extract pages
        pages = extract_text_with_pages(pdf_path)
        if not pages:
            continue
        
        # Chunk pages
        chunks = chunk_pages(pages, max_chunk_size=chunk_size)
        logger.info(f"    Split into {len(chunks)} chunks")
        
        # Generate Q&A for each chunk
        for chunk_idx, chunk in enumerate(chunks):
            logger.info(f"    Processing chunk {chunk_idx + 1}/{len(chunks)} (pages {chunk['page_start']}-{chunk['page_end']})")
            
            documents = await generate_dual_qa_pairs(
                chunk=chunk,
                intent=intent,
                max_questions=max_questions_per_chunk
            )
            
            all_documents.extend(documents)
            
            # Rate limiting
            await asyncio.sleep(0.5)
    
    logger.info(f"\n  ✅ Total documents generated for {intent}: {len(all_documents)}")
    
    # Save to JSON file
    output_file = OUTPUT_DIR / f"{intent}_qa.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_documents, f, indent=2, ensure_ascii=False)
    logger.info(f"  📄 Saved to: {output_file}")
    
    # Index to OpenSearch if not dry run
    if not dry_run and all_documents:
        await index_documents_to_opensearch(all_documents, kb_index)
    
    return len(all_documents), all_documents


async def index_documents_to_opensearch(documents: List[Dict], index_name: str):
    """Index documents to OpenSearch with embeddings."""
    try:
        from services.knowledge_base import get_knowledge_base, create_index_if_not_exists
        
        logger.info(f"\n  📥 Indexing {len(documents)} documents to {index_name}...")
        
        # Create index if needed
        await create_index_if_not_exists(index_name)
        
        kb = get_knowledge_base(use_vectors=True, index_name=index_name)
        
        indexed = 0
        for doc in documents:
            # Create content for embedding
            content = f"Question: {doc['question']}\n\nAnswer: {doc['answer']}"
            
            # Create document for KB
            from models.schemas_deprecated import KnowledgeDocument, ContentType
            
            kb_doc = KnowledgeDocument(
                title=doc['question'][:100],
                content=content,
                content_type=ContentType.QA_PAIR,
                source_url=doc['source_file'],
                metadata={
                    "question": doc['question'],
                    "answer": doc['answer'],
                    "answer_type": doc['answer_type'],
                    "intent": doc['intent'],
                    "section": doc.get('section', ''),
                    "page_start": doc.get('page_start'),
                    "page_end": doc.get('page_end'),
                    "verbatim_text": doc.get('verbatim_text', '')
                }
            )
            
            await kb.add_document(kb_doc)
            indexed += 1
            
            if indexed % 10 == 0:
                logger.info(f"    Indexed {indexed}/{len(documents)} documents...")
        
        logger.info(f"  ✅ Successfully indexed {indexed} documents to {index_name}")
        
    except Exception as e:
        logger.error(f"  ❌ Error indexing to OpenSearch: {e}")
        raise


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate Q&A pairs for per-intent knowledge bases')
    parser.add_argument('--intent', '-i', type=str, default=None,
                        help='Process a single intent (e.g., medication_info)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='Process all intents')
    parser.add_argument('--dry-run', '-d', action='store_true',
                        help='Generate Q&A but do not index to OpenSearch')
    parser.add_argument('--max-questions', '-q', type=int, default=0,
                        help='Maximum questions per chunk (default: 0 = no limit, generate all relevant)')
    parser.add_argument('--chunk-size', '-c', type=int, default=5000,
                        help='Maximum characters per chunk (default: 5000, smaller = more focused)')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List available intents from mapping')
    parser.add_argument('--leaflet', type=str, default=None,
                        help='Process only a specific leaflet (filename, e.g., bcc20-tamoxifen-web.pdf)')
    args = parser.parse_args()
    
    # Load mapping
    mapping = load_intent_mapping()
    
    if args.list:
        logger.info("Available intents:")
        for intent, config in mapping.items():
            leaflet_count = len(config.get('leaflets', []))
            logger.info(f"  - {intent}: {leaflet_count} leaflets → {config.get('kb_index', 'N/A')}")
        return
    
    if not args.intent and not args.all:
        parser.print_help()
        logger.info("\nExamples:")
        logger.info("  python scripts/generate_intent_qa.py --intent medication_info --dry-run")
        logger.info("  python scripts/generate_intent_qa.py --all")
        return
    
    logger.info("="*60)
    logger.info("PER-INTENT Q&A GENERATION")
    logger.info("="*60)
    logger.info(f"Mapping file: {MAPPING_FILE}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Max questions per chunk: {args.max_questions}")
    logger.info("="*60)
    
    total_docs = 0
    
    if args.intent:
        # Process single intent
        count, _ = await process_intent(
            intent=args.intent,
            mapping=mapping,
            dry_run=args.dry_run,
            max_questions_per_chunk=args.max_questions,
            single_leaflet=args.leaflet,
            chunk_size=args.chunk_size
        )
        total_docs = count
    
    elif args.all:
        # Process all intents
        for intent in mapping.keys():
            if intent == 'unknown':
                continue  # Skip unknown intent
            
            count, _ = await process_intent(
                intent=intent,
                mapping=mapping,
                dry_run=args.dry_run,
                max_questions_per_chunk=args.max_questions
            )
            total_docs += count
            
            # Rate limiting between intents
            await asyncio.sleep(1)
    
    logger.info("\n" + "="*60)
    logger.info("GENERATION COMPLETE")
    logger.info(f"Total documents generated: {total_docs}")
    logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())

