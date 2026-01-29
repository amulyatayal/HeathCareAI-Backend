"""
Generate Q&A pairs for per-intent knowledge bases.
Creates ONE document per question with BOTH answer variants:
  - derived_answer: AI-written answer synthesized from leaflet content
  - citation_only: Verbatim excerpt from PDF (no paraphrasing)
  - source_excerpt: The original source text (same as citation_only)

This consolidated format reduces KB size by ~50% while preserving both answer types.
The retrieval agent uses derived_answer for semantic search, and the reasoning agent
selects which answer to use at response time based on intent.

Usage:
  # Generate Q&A for a single intent (for testing)
  python scripts/kb-preprocessing/generate_intent_qa.py --intent medication_info
  
  # Generate Q&A for all intents
  python scripts/kb-preprocessing/generate_intent_qa.py --all
  
  # Dry run (no indexing)
  python scripts/kb-preprocessing/generate_intent_qa.py --intent medication_info --dry-run
  
  # Ingest existing Q&A file to OpenSearch (without regenerating)
  python scripts/kb-preprocessing/generate_intent_qa.py --intent cancer_treatment --ingest-only
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
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from config import bedrock
from config.pipeline_config import IntentCategory

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


# ================================
# Configuration
# ================================

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "sample" / "raw" / "Leaflets"
MAPPING_FILE = Path(__file__).parent.parent.parent / "config" / "intent_leaflets_mapping.json"
URL_MAPPING_FILE = Path(__file__).parent.parent.parent / "data" / "leaflets_URL_mapping.csv"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "intent_qa"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Category descriptions for better Q&A context
CATEGORY_DESCRIPTIONS = {
    "symptoms": {
        "description": "Common symptoms experienced by breast cancer patients, including physical symptoms, side effects, and warning signs",
        "question_focus": "What symptoms to expect, how to manage them, when to seek help",
        "answer_style": "Empathetic, reassuring, practical advice"
    },
    "surgery_procedures": {
        "description": "Surgical procedures for breast cancer treatment including mastectomy, lumpectomy, reconstruction options",
        "question_focus": "What to expect before, during, and after surgery",
        "answer_style": "Clear, informative, preparing patients for procedures"
    },
    "drains_wound_care": {
        "description": "Post-operative care including wound care, drain management, and recovery",
        "question_focus": "How to care for wounds and drains, signs of complications",
        "answer_style": "Practical, step-by-step guidance"
    },
    "cancer_treatment": {
        "description": "All aspects of breast cancer treatment including chemotherapy, radiotherapy, hormone therapy",
        "question_focus": "Treatment options, what to expect, managing treatment journey",
        "answer_style": "Comprehensive, supportive, informative"
    },
    "medication_info": {
        "description": "Information about breast cancer medications including hormone therapies, chemotherapy drugs",
        "question_focus": "How medications work, side effects, dosing, interactions",
        "answer_style": "Factual, clear, addressing common concerns"
    },
    "side_effects": {
        "description": "Side effects from breast cancer treatments and how to manage them",
        "question_focus": "What side effects to expect, how to cope, when to seek help",
        "answer_style": "Supportive, practical coping strategies"
    },
    "pre_surgery_prehab": {
        "description": "Preparing for breast cancer surgery, prehabilitation exercises, what to expect",
        "question_focus": "How to prepare physically and mentally for surgery",
        "answer_style": "Encouraging, practical preparation advice"
    },
    "post_surgery_recovery": {
        "description": "Recovery after breast cancer surgery, exercises, returning to normal activities",
        "question_focus": "Recovery timeline, exercises, getting back to daily life",
        "answer_style": "Supportive, gradual progress, realistic expectations"
    },
    "follow_up_care": {
        "description": "Ongoing care after treatment, check-ups, monitoring, life after cancer",
        "question_focus": "What follow-up care involves, staying healthy, emotional wellbeing",
        "answer_style": "Reassuring, forward-looking, empowering"
    },
    "nutrition": {
        "description": "Diet and nutrition advice for breast cancer patients during and after treatment",
        "question_focus": "What to eat, dietary changes, supplements, healthy eating",
        "answer_style": "Practical, evidence-based, encouraging healthy choices"
    },
    "exercise": {
        "description": "Physical activity and exercise recommendations for breast cancer patients",
        "question_focus": "Safe exercises, benefits of activity, getting started",
        "answer_style": "Encouraging, safe, progressive approach"
    },
    "emotional_support": {
        "description": "Emotional and psychological support for patients and families",
        "question_focus": "Coping with emotions, getting support, mental wellbeing",
        "answer_style": "Compassionate, validating, resource-focused"
    },
    "clothing": {
        "description": "Clothing, bras, and prostheses after breast surgery",
        "question_focus": "Finding comfortable clothing, prosthesis options, fitting bras",
        "answer_style": "Practical, body-positive, helpful resources"
    },
    "diagnosis_testing": {
        "description": "Breast cancer diagnosis process, tests, understanding results",
        "question_focus": "What tests involve, understanding diagnosis, next steps",
        "answer_style": "Clear, informative, reducing anxiety"
    },
    "admin_logistics": {
        "description": "Practical matters like appointments, travel, financial support",
        "question_focus": "Navigating healthcare system, practical support available",
        "answer_style": "Helpful, resource-focused, practical"
    },
    "safety_red_flags": {
        "description": "Warning signs requiring immediate medical attention",
        "question_focus": "When to seek urgent help, recognizing serious symptoms",
        "answer_style": "Clear, action-oriented, emphasizing safety"
    },
    "statistics": {
        "description": "Statistics about breast cancer including survival rates, risk factors, and research data. IMPORTANT: Focus on providing context and hope rather than raw numbers.",
        "question_focus": "Understanding statistics in context, risk factors, research findings, survival information",
        "answer_style": "Contextual, hopeful, explaining what numbers mean for individuals. Avoid quoting specific percentages without context.",
        "guidelines": "Don't just quote numbers - explain what they mean. Focus on how statistics relate to individual circumstances. Emphasize that statistics are averages and every person's situation is unique."
    }
}


def load_intent_mapping() -> Dict:
    """Load the intent-to-leaflets mapping configuration."""
    with open(MAPPING_FILE, 'r') as f:
        mapping = json.load(f)
    # Remove metadata keys
    return {k: v for k, v in mapping.items() if not k.startswith('_')}


def get_all_unique_leaflets(mapping: Dict) -> List[str]:
    """
    Collect all unique leaflet filenames from all intents.
    
    Returns:
        Sorted list of unique leaflet filenames
    """
    all_leaflets = set()
    for intent, config in mapping.items():
        if intent.startswith('_') or intent == 'unknown':
            continue
        for leaflet in config.get('leaflets', []):
            # Clean up any trailing commas or whitespace
            clean_leaflet = leaflet.strip().rstrip(',')
            if clean_leaflet:
                all_leaflets.add(clean_leaflet)
    
    unique_list = sorted(list(all_leaflets))
    logger.info(f"Found {len(unique_list)} unique leaflets across all intents")
    return unique_list


def load_url_mapping() -> Dict[str, Dict]:
    """Load the leaflet filename to URL mapping."""
    import csv
    url_mapping = {}
    
    if not URL_MAPPING_FILE.exists():
        logger.warning(f"URL mapping file not found: {URL_MAPPING_FILE}")
        return url_mapping
    
    with open(URL_MAPPING_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            leaflet_name = row.get('leaflet_name', '').strip()
            url = row.get('url', '').strip()
            source = row.get('source', '').strip()
            
            if leaflet_name and url:
                info = {
                    'url': url,
                    'source': source,
                    'display_name': leaflet_name
                }
                
                # Store by leaflet_name (lowercase for matching)
                url_mapping[leaflet_name.lower()] = info
                
                # Also store by PDF filename extracted from URL if it ends with .pdf
                if url.endswith('.pdf'):
                    filename_from_url = url.split('/')[-1].lower()
                    if filename_from_url not in url_mapping:
                        url_mapping[filename_from_url] = info
    
    logger.info(f"Loaded {len(url_mapping)} URL mappings")
    return url_mapping


def get_leaflet_url(filename: str, url_mapping: Dict) -> Dict:
    """Get URL info for a leaflet filename."""
    # Try exact match (lowercase)
    key = filename.lower()
    if key in url_mapping:
        return url_mapping[key]
    
    # Try matching by partial filename
    for map_key, info in url_mapping.items():
        if key in map_key or map_key in key:
            return info
    
    return {'url': '', 'source': '', 'display_name': filename}


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
    source_url_info: Dict = None,
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
        
        # Get category-specific context
        category_info = CATEGORY_DESCRIPTIONS.get(intent, {})
        category_description = category_info.get('description', f'Information about {intent.replace("_", " ")}')
        question_focus = category_info.get('question_focus', 'General patient questions')
        answer_style = category_info.get('answer_style', 'Clear and supportive')
        guidelines = category_info.get('guidelines', '')
        
        question_instruction = f"Create up to {max_questions} question-answer pairs" if max_questions > 0 else "Create ALL relevant question-answer pairs - aim for comprehensive coverage of the content"
        
        # Build category-specific guidelines
        category_guidelines = f"""
CATEGORY-SPECIFIC GUIDELINES:
- Question Focus: {question_focus}
- Answer Style: {answer_style}"""
        if guidelines:
            category_guidelines += f"\n- Special Instructions: {guidelines}"
        
        prompt = f"""You are a medical content specialist creating educational Q&A pairs from a breast cancer patient information leaflet.

KNOWLEDGE BASE CONTEXT:
You are building a knowledge base for: "{intent.upper()}"
Purpose: {category_description}
{category_guidelines}

TASK: {question_instruction} from the following document section.
Your goal is to extract MAXIMUM COVERAGE - create Q&A pairs for every distinct piece of patient-relevant information.
For EACH question, you must provide TWO answer types:

1. **generated_answer**: A comprehensive, empathetic answer that explains the information clearly to patients. Use natural language, be supportive, and synthesize information from the source. Style: {answer_style}

2. **citation_answer**: The EXACT verbatim text from the document that answers the question. Copy word-for-word without any changes or paraphrasing. This must be a direct quote.

INTENT CATEGORY: {intent}
This Q&A should be relevant to questions about: {question_focus}

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

QUESTIONS TO SKIP (do NOT create these):
- Do NOT create questions about what the leaflet/booklet covers or contains
- Do NOT create questions like "What is this leaflet about?" or "What topics are covered in this booklet?"
- Do NOT create questions about the document structure, authorship, or publication details
- Focus ONLY on the actual medical/health information content that helps patients

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
            repaired = json_str
            repaired = re.sub(r',\s*]', ']', repaired)  # Remove trailing commas in arrays
            repaired = re.sub(r',\s*}', '}', repaired)  # Remove trailing commas in objects
            repaired = re.sub(r'}\s*{', '},{', repaired)  # Add missing comma between objects
            repaired = re.sub(r'"\s*"', '","', repaired)  # Add missing comma between strings
            repaired = re.sub(r'(\d)\s*"', r'\1,"', repaired)  # Add comma after numbers before strings
            repaired = re.sub(r'"\s*(\d)', r'",\1', repaired)  # Add comma after strings before numbers
            repaired = re.sub(r'}\s*"', '},"', repaired)  # Add comma after } before "
            repaired = re.sub(r']\s*"', '],"', repaired)  # Add comma after ] before "
            
            try:
                qa_pairs = json.loads(repaired)
                logger.info("    Repair successful!")
            except json.JSONDecodeError as e2:
                # Try to extract individual JSON objects
                logger.warning(f"    Standard repair failed: {e2}. Trying object extraction...")
                qa_pairs = []
                obj_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                objects = re.findall(obj_pattern, json_str)
                for obj_str in objects:
                    try:
                        obj = json.loads(obj_str)
                        if 'question' in obj:  # Valid Q&A object
                            qa_pairs.append(obj)
                    except:
                        pass
                if qa_pairs:
                    logger.info(f"    Extracted {len(qa_pairs)} objects via fallback")
                else:
                    raise e2
        
        # Create ONE document per Q&A with both answer variants
        documents = []
        for qa in qa_pairs:
            # The citation_answer is the verbatim source text
            citation_only = qa.get("citation_answer", "")
            
            # Get URL info
            url_info = source_url_info or {}
            
            # Single consolidated document with both answer types
            doc = {
                "question": qa.get("question", ""),
                "derived_answer": qa.get("generated_answer", ""),  # AI-synthesized answer
                "citation_only": citation_only,  # Verbatim quote from source
                "source_excerpt": citation_only,  # Same as citation_only (for provenance)
                "source_file": chunk["source_file"],
                "source_url": url_info.get("url", ""),
                "source_name": url_info.get("source", ""),
                "source_display_name": url_info.get("display_name", chunk["source_file"]),
                "section": qa.get("section", ""),
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "intent": intent,
                "created_at": datetime.utcnow().isoformat(),
                "relevance_score": qa.get("relevance_score", 0.8),
            }
            documents.append(doc)
        
        logger.info(f"    Generated {len(qa_pairs)} Q&A documents (consolidated format)")
        return documents
        
    except Exception as e:
        logger.error(f"    Error generating Q&A: {e}")
        return []


async def process_intent(
    intent: str,
    mapping: Dict,
    url_mapping: Dict = None,
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
    
    # Get category description
    category_info = CATEGORY_DESCRIPTIONS.get(intent, {})
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing intent: {intent}")
    logger.info(f"Description: {category_info.get('description', 'N/A')}")
    logger.info(f"KB index: {kb_index}")
    logger.info(f"Leaflets: {len(leaflets)}")
    logger.info(f"{'='*60}")
    
    if not leaflets:
        logger.warning(f"  No leaflets configured for intent: {intent}")
        return 0, []
    
    # Load URL mapping if not provided
    if url_mapping is None:
        url_mapping = load_url_mapping()
    
    all_documents = []
    
    for leaflet_name in leaflets:
        pdf_path = DATA_DIR / leaflet_name
        
        if not pdf_path.exists():
            logger.warning(f"  Leaflet not found: {leaflet_name}")
            continue
        
        logger.info(f"\n  Processing: {leaflet_name}")
        
        # Get URL info for this leaflet
        source_url_info = get_leaflet_url(leaflet_name, url_mapping)
        if source_url_info.get('url'):
            logger.info(f"    Source URL: {source_url_info['url'][:60]}...")
        
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
                source_url_info=source_url_info,
                max_questions=max_questions_per_chunk
            )
            
            all_documents.extend(documents)
            
            # Rate limiting
            await asyncio.sleep(0.5)
    
    logger.info(f"\n  ✅ Total documents generated for {intent}: {len(all_documents)}")
    
    # Save to JSON file
    output_file = OUTPUT_DIR / f"{intent}_qa.json"
    
    # If processing single leaflet, merge with existing data
    if single_leaflet and output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing_docs = json.load(f)
            # Remove any existing docs for this leaflet (to avoid duplicates)
            existing_docs = [d for d in existing_docs if d.get("source_file") != single_leaflet]
            all_documents = existing_docs + all_documents
            logger.info(f"  📎 Merged with existing data: {len(existing_docs)} + {len(all_documents) - len(existing_docs)} = {len(all_documents)} docs")
        except Exception as e:
            logger.warning(f"  Could not merge with existing: {e}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_documents, f, indent=2, ensure_ascii=False)
    logger.info(f"  📄 Saved to: {output_file}")
    
    # Index to OpenSearch if not dry run
    if not dry_run and all_documents:
        await index_documents_to_opensearch(all_documents, kb_index)
    
    return len(all_documents), all_documents


async def process_all_leaflets_as_one_kb(
    leaflets: List[str],
    url_mapping: Dict = None,
    dry_run: bool = True,
    max_questions_per_chunk: int = 0,
    chunk_size: int = 2000
) -> Tuple[int, List[Dict]]:
    """
    Process ALL leaflets as a single unified knowledge base (medical_all_kb).
    
    This creates one comprehensive KB from all available leaflets, using smaller
    chunk sizes for maximum Q&A coverage.
    
    Args:
        leaflets: List of unique leaflet filenames to process
        url_mapping: Pre-loaded URL mapping dict
        dry_run: If True, only generate JSON (no OpenSearch indexing)
        max_questions_per_chunk: Max Q&A pairs per chunk (0 = no limit)
        chunk_size: Maximum characters per chunk (smaller = more Q&A pairs)
    
    Returns:
        Tuple of (document_count, documents_list)
    """
    kb_index = "medical_all_kb"
    intent = "medical"  # Generic intent for unified KB
    
    logger.info(f"\n{'='*60}")
    logger.info(f"UNIFIED KNOWLEDGE BASE GENERATION: {kb_index}")
    logger.info(f"{'='*60}")
    logger.info(f"Total unique leaflets: {len(leaflets)}")
    logger.info(f"Chunk size: {chunk_size} chars (smaller = more Q&A pairs)")
    logger.info(f"Max questions per chunk: {'unlimited' if max_questions_per_chunk == 0 else max_questions_per_chunk}")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"{'='*60}")
    
    if not leaflets:
        logger.error("No leaflets to process")
        return 0, []
    
    # Load URL mapping if not provided
    if url_mapping is None:
        url_mapping = load_url_mapping()
    
    all_documents = []
    processed_count = 0
    skipped_count = 0
    
    for leaflet_idx, leaflet_name in enumerate(leaflets):
        pdf_path = DATA_DIR / leaflet_name
        
        if not pdf_path.exists():
            logger.warning(f"  [{leaflet_idx+1}/{len(leaflets)}] Leaflet not found: {leaflet_name}")
            skipped_count += 1
            continue
        
        logger.info(f"\n  [{leaflet_idx+1}/{len(leaflets)}] Processing: {leaflet_name}")
        
        # Get URL info for this leaflet
        source_url_info = get_leaflet_url(leaflet_name, url_mapping)
        if source_url_info.get('url'):
            logger.info(f"    Source URL: {source_url_info['url'][:60]}...")
        
        # Extract pages
        pages = extract_text_with_pages(pdf_path)
        if not pages:
            logger.warning(f"    No text extracted from {leaflet_name}")
            skipped_count += 1
            continue
        
        # Chunk pages with smaller chunk size for more Q&A pairs
        chunks = chunk_pages(pages, max_chunk_size=chunk_size)
        logger.info(f"    Split into {len(chunks)} chunks (@ {chunk_size} chars)")
        
        # Generate Q&A for each chunk
        leaflet_docs = 0
        for chunk_idx, chunk in enumerate(chunks):
            logger.info(f"    Processing chunk {chunk_idx + 1}/{len(chunks)} (pages {chunk['page_start']}-{chunk['page_end']})")
            
            documents = await generate_dual_qa_pairs(
                chunk=chunk,
                intent=intent,
                source_url_info=source_url_info,
                max_questions=max_questions_per_chunk
            )
            
            all_documents.extend(documents)
            leaflet_docs += len(documents)
            
            # Rate limiting to avoid API throttling
            await asyncio.sleep(0.5)
        
        logger.info(f"    ✓ Generated {leaflet_docs} Q&A pairs from {leaflet_name}")
        processed_count += 1
    
    logger.info(f"\n{'='*60}")
    logger.info(f"GENERATION SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"  Leaflets processed: {processed_count}/{len(leaflets)}")
    logger.info(f"  Leaflets skipped: {skipped_count}")
    logger.info(f"  Total Q&A documents: {len(all_documents)}")
    logger.info(f"{'='*60}")
    
    # Save to JSON file
    output_file = OUTPUT_DIR / f"{kb_index}_qa.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_documents, f, indent=2, ensure_ascii=False)
    logger.info(f"  📄 Saved to: {output_file}")
    
    # Index to OpenSearch if not dry run
    if not dry_run and all_documents:
        await index_documents_to_opensearch(all_documents, kb_index)
    
    return len(all_documents), all_documents


async def index_documents_to_opensearch(documents: List[Dict], index_name: str, batch_size: int = 50):
    """Index documents to OpenSearch with embeddings using bulk indexing."""
    try:
        from services.knowledge_base import create_index_if_not_exists, EmbeddingService
        from config import opensearch
        from opensearchpy.helpers import bulk
        import hashlib
        
        logger.info(f"\n  📥 Indexing {len(documents)} documents to {index_name}...")
        logger.info(f"  Using batch size: {batch_size}")
        
        # Create index if needed (sync function)
        create_index_if_not_exists(index_name)
        
        # Get OpenSearch client directly for bulk operations
        client = opensearch()
        
        # Initialize embedding service
        embedding_service = EmbeddingService()
        
        # Map intent to query category
        intent_to_category = {
            "cancer_treatment": "treatment",
            "medication_info": "medication",
            "side_effects": "side_effects",
            "symptoms": "symptoms",
            "nutrition": "nutrition",
            "emotional_support": "emotional_support",
            "follow_up_care": "follow_up_care",
            "statistics": "general",
            "surgery_procedures": "treatment",
            "drains_wound_care": "treatment",
            "pre_surgery_prehab": "treatment",
            "post_surgery_recovery": "treatment",
            "exercise": "lifestyle",
            "clothing": "lifestyle",
            "diagnosis_testing": "symptoms",
            "admin_logistics": "general",
            "safety_red_flags": "symptoms",
        }
        
        total_indexed = 0
        failed = 0
        
        # Process in batches
        for batch_start in range(0, len(documents), batch_size):
            batch_end = min(batch_start + batch_size, len(documents))
            batch = documents[batch_start:batch_end]
            
            logger.info(f"    Processing batch {batch_start//batch_size + 1}: documents {batch_start+1}-{batch_end}...")
            
            # Generate embeddings for the batch
            bulk_actions = []
            for doc in batch:
                # Create content for embedding using derived_answer (AI-synthesized, better for semantic search)
                derived_answer = doc.get('derived_answer', doc.get('answer', ''))  # Fallback for old format
                content = f"Question: {doc['question']}\n\nAnswer: {derived_answer}"
                
                # Generate embedding
                try:
                    embedding = embedding_service.create_embedding(content)
                    if not embedding:
                        embedding = [0.0] * 1024  # Default zero vector
                except Exception as e:
                    logger.warning(f"    Failed to generate embedding: {e}")
                    embedding = [0.0] * 1024  # Default zero vector
                
                # Get category from intent
                intent = doc.get('intent', '')
                category = intent_to_category.get(intent, 'general')
                
                # Generate document ID from content hash
                doc_id = str(hash(content))
                
                # Get citation_only (fallback to source_excerpt for old format)
                citation_only = doc.get('citation_only', doc.get('source_excerpt', ''))
                
                # Build OpenSearch document (consolidated format)
                os_doc = {
                    "_index": index_name,
                    "_id": doc_id,
                    "_source": {
                        "title": doc['question'][:100],
                        "content": content,
                        "content_type": "faq",
                        "category": category,
                        "source_url": doc.get('source_url', doc.get('source_file', '')),
                        "embedding": embedding,  # Field name must match index mapping
                        "metadata": {
                            "question": doc['question'],
                            "derived_answer": derived_answer,  # AI-synthesized answer
                            "citation_only": citation_only,  # Verbatim quote for citation mode
                            "source_excerpt": doc.get('source_excerpt', citation_only),  # Original source text
                            "intent": intent,
                            "section": doc.get('section', ''),
                            "page_start": doc.get('page_start'),
                            "page_end": doc.get('page_end'),
                            "source_file": doc.get('source_file', ''),
                            "source_name": doc.get('source_name', ''),
                            "source_display_name": doc.get('source_display_name', ''),
                            "source_url": doc.get('source_url', ''),
                            "relevance_score": doc.get('relevance_score', 0.9)
                        }
                    }
                }
                bulk_actions.append(os_doc)
            
            # Bulk index
            try:
                success, errors = bulk(client, bulk_actions, raise_on_error=False, request_timeout=120)
                total_indexed += success
                if errors:
                    failed += len(errors)
                    logger.warning(f"    Batch had {len(errors)} errors")
                logger.info(f"    Batch complete: {success} indexed, {total_indexed}/{len(documents)} total")
            except Exception as e:
                logger.error(f"    Bulk index error: {e}")
                failed += len(batch)
        
        logger.info(f"  ✅ Successfully indexed {total_indexed} documents to {index_name}")
        if failed > 0:
            logger.warning(f"  ⚠️  {failed} documents failed to index")
        
    except Exception as e:
        logger.error(f"  ❌ Error indexing to OpenSearch: {e}")
        raise


async def ingest_existing_qa(intent: str, mapping: Dict, clear_index: bool = False):
    """Ingest an existing Q&A file to OpenSearch without regenerating."""
    logger.info("="*60)
    logger.info(f"INGESTING EXISTING Q&A: {intent}")
    logger.info("="*60)
    
    # Get KB index from mapping
    intent_config = mapping.get(intent)
    if not intent_config:
        logger.error(f"Intent '{intent}' not found in mapping")
        return
    
    kb_index = intent_config.get('kb_index', f'kb_{intent}')
    qa_file = OUTPUT_DIR / f"{intent}_qa.json"
    
    if not qa_file.exists():
        logger.error(f"Q&A file not found: {qa_file}")
        return
    
    # Load existing Q&A
    with open(qa_file, 'r') as f:
        documents = json.load(f)
    
    logger.info(f"  Loaded {len(documents)} documents from {qa_file.name}")
    logger.info(f"  Target index: {kb_index}")
    
    # Clear index if requested
    if clear_index:
        from config import opensearch
        client = opensearch()
        try:
            if client.indices.exists(index=kb_index):
                logger.info(f"  Deleting existing index: {kb_index}")
                client.indices.delete(index=kb_index)
                logger.info(f"  Index deleted. Will be recreated with correct mapping.")
        except Exception as e:
            logger.warning(f"  Could not delete index: {e}")
    
    # Index to OpenSearch
    await index_documents_to_opensearch(documents, kb_index)
    
    logger.info("\n" + "="*60)
    logger.info(f"INGESTION COMPLETE: {len(documents)} documents → {kb_index}")
    logger.info("="*60)


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
    parser.add_argument('--ingest-only', action='store_true',
                        help='Ingest existing Q&A file to OpenSearch without regenerating')
    parser.add_argument('--clear-index', action='store_true',
                        help='Clear the index before ingesting (use with --ingest-only)')
    parser.add_argument('--max-questions', '-q', type=int, default=0,
                        help='Maximum questions per chunk (default: 0 = no limit, generate all relevant)')
    parser.add_argument('--chunk-size', '-c', type=int, default=5000,
                        help='Maximum characters per chunk (default: 5000, smaller = more focused)')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List available intents from mapping')
    parser.add_argument('--leaflet', type=str, default=None,
                        help='Process only a specific leaflet (filename, e.g., bcc20-tamoxifen-web.pdf)')
    parser.add_argument('--all-leaflets', action='store_true',
                        help='Process ALL unique leaflets from all intents as a single unified KB (medical_all_kb)')
    args = parser.parse_args()
    
    # Load mapping
    mapping = load_intent_mapping()
    
    if args.list:
        logger.info("Available intents:")
        for intent, config in mapping.items():
            leaflet_count = len(config.get('leaflets', []))
            logger.info(f"  - {intent}: {leaflet_count} leaflets → {config.get('kb_index', 'N/A')}")
        return
    
    if not args.intent and not args.all and not args.all_leaflets:
        parser.print_help()
        logger.info("\nExamples:")
        logger.info("  python scripts/kb-preprocessing/generate_intent_qa.py --intent medication_info --dry-run")
        logger.info("  python scripts/kb-preprocessing/generate_intent_qa.py --all")
        logger.info("  python scripts/kb-preprocessing/generate_intent_qa.py --intent cancer_treatment --ingest-only")
        logger.info("  python scripts/kb-preprocessing/generate_intent_qa.py --all-leaflets --chunk-size 2000 --dry-run")
        return
    
    # Handle ingest-only mode
    if args.ingest_only:
        if not args.intent:
            logger.error("--ingest-only requires --intent to specify which Q&A file to ingest")
            return
        
        await ingest_existing_qa(args.intent, mapping, clear_index=args.clear_index)
        return
    
    # Handle --all-leaflets mode: unified KB from all unique leaflets
    if args.all_leaflets:
        all_leaflets = get_all_unique_leaflets(mapping)
        url_mapping = load_url_mapping()
        
        count, _ = await process_all_leaflets_as_one_kb(
            leaflets=all_leaflets,
            url_mapping=url_mapping,
            dry_run=args.dry_run,
            max_questions_per_chunk=args.max_questions,
            chunk_size=args.chunk_size
        )
        
        logger.info("\n" + "="*60)
        logger.info("UNIFIED KB GENERATION COMPLETE")
        logger.info(f"Total Q&A documents: {count}")
        logger.info(f"Output: data/intent_qa/medical_all_kb_qa.json")
        logger.info("="*60)
        return
    
    logger.info("="*60)
    logger.info("PER-INTENT Q&A GENERATION")
    logger.info("="*60)
    logger.info(f"Mapping file: {MAPPING_FILE}")
    logger.info(f"URL mapping file: {URL_MAPPING_FILE}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Max questions per chunk: {args.max_questions}")
    logger.info("="*60)
    
    # Load URL mapping once for all processing
    url_mapping = load_url_mapping()
    
    total_docs = 0
    
    if args.intent:
        # Process single intent
        count, _ = await process_intent(
            intent=args.intent,
            mapping=mapping,
            url_mapping=url_mapping,
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
                url_mapping=url_mapping,
                dry_run=args.dry_run,
                max_questions_per_chunk=args.max_questions,
                chunk_size=args.chunk_size
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
