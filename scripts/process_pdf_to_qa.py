"""
Process PDF medical leaflets into Q&A pairs for knowledge base
Generates structured Q&A with medical accuracy (temperature=0)
"""

import sys
import json
import asyncio
import logging
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import re

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Query categories as specified
QUERY_CATEGORIES = [
    "SYMPTOMS",
    "SURGERY_PROCEDURES",
    "DRAINS_WOUND_CARE",
    "CANCER_TREATMENT",
    "MEDICATION",
    "SIDE_EFFECTS",
    "PRE_SURGERY_PREHAB",
    "POST_SURGERY_RECOVERY",
    "FOLLOW_UP_CARE",
    "LIFESTYLE",
    "NUTRITION",
    "EMOTIONAL_SUPPORT",
    "DIAGNOSIS_TESTING",
    "ADMIN_LOGISTICS",
    "SAFETY_RED_FLAGS"
]

# CSV columns from ProcessedQ&A-2
CSV_COLUMNS = [
    "Sno.",
    "Question (100 words)",
    "Answer (Max 2000 words)",
    "Question Category (Refer Sheet 2)",
    "Applicable to Pathways",
    "Pathway Stage",
    "Source of Data (Preferable URL)",
    "Actual Excerpt from the Source Data",
    "Hospitals Applicable",
    "Date",
    "Author Name",
    "Reviewed By",
    "Expiry Date"
]


def extract_text_from_pdf(pdf_path: Path) -> Optional[str]:
    """Extract text content from a PDF file"""
    try:
        logger.info(f"Extracting text from: {pdf_path.name}")
        
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text_content = []
            
            for page_num, page in enumerate(pdf_reader.pages):
                text = page.extract_text()
                if text.strip():
                    text_content.append(text)
            
            full_text = "\n\n".join(text_content)
            
            logger.info(f"  Extracted {len(pdf_reader.pages)} pages, {len(full_text)} characters")
            return full_text
            
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path.name}: {e}")
        return None


def chunk_text(text: str, max_chunk_size: int = 8000) -> List[str]:
    """Split text into chunks for processing"""
    # Split by paragraphs
    paragraphs = text.split('\n\n')
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for para in paragraphs:
        para_size = len(para)
        
        if current_size + para_size > max_chunk_size and current_chunk:
            chunks.append('\n\n'.join(current_chunk))
            current_chunk = [para]
            current_size = para_size
        else:
            current_chunk.append(para)
            current_size += para_size
    
    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))
    
    return chunks


async def generate_qa_pairs_from_text(
    text: str,
    source_filename: str,
    max_questions: int = 10
) -> List[Dict[str, str]]:
    """Use AI to generate Q&A pairs from medical text"""
    
    try:
        client = bedrock()
        
        # Prepare prompt for Q&A generation
        prompt = f"""You are a medical content specialist creating educational Q&A pairs from breast cancer patient information leaflets.

TASK: Extract or generate {max_questions} question-answer pairs from the following medical document.

REQUIREMENTS:
1. Questions should be natural patient questions (max 100 words)
2. Answers must be factual, accurate, and comprehensive (max 2000 words)
3. Each Q&A must include:
   - A clear question a patient would ask
   - A detailed, evidence-based answer
   - The most appropriate category from: {', '.join(QUERY_CATEGORIES)}
   - A direct excerpt from the source that supports the answer

GUIDELINES:
- Focus on practical, actionable information
- Use empathetic, supportive language
- Be specific and avoid vague statements
- Include relevant medical terms with patient-friendly explanations
- Cite specific information from the document

SOURCE DOCUMENT: {source_filename}

DOCUMENT CONTENT:
{text[:15000]}

OUTPUT FORMAT (JSON array):
[
  {{
    "question": "Patient's question here",
    "answer": "Comprehensive answer here",
    "category": "CATEGORY_NAME",
    "excerpt": "Direct quote from document supporting this answer"
  }}
]

Generate the Q&A pairs now:"""

        # Call Bedrock with temperature=0 for factual accuracy
        body = json.dumps({
            "inferenceConfig": {
                "max_new_tokens": 4000,
                "temperature": 0.0  # Factual, deterministic output
            },
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ]
        })
        
        logger.info(f"  Generating Q&A pairs from {source_filename}...")
        response = client.invoke_model(
            modelId="amazon.nova-pro-v1:0",
            body=body
        )
        
        response_body = json.loads(response['body'].read())
        ai_response = response_body['output']['message']['content'][0]['text']
        
        # Extract JSON from response
        json_match = re.search(r'\[[\s\S]*\]', ai_response)
        if json_match:
            qa_pairs = json.loads(json_match.group(0))
            logger.info(f"  Generated {len(qa_pairs)} Q&A pairs")
            return qa_pairs
        else:
            logger.warning(f"  Could not parse JSON from AI response")
            return []
            
    except Exception as e:
        logger.error(f"Error generating Q&A: {e}")
        return []


async def process_pdf_file(
    pdf_path: Path,
    start_sno: int,
    author: str = "Healthcare AI Team",
    max_questions_per_chunk: int = 15
) -> List[Dict[str, str]]:
    """Process a single PDF file into Q&A pairs"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {pdf_path.name}")
    logger.info(f"{'='*60}")
    
    # Extract text
    text = extract_text_from_pdf(pdf_path)
    if not text or len(text) < 100:
        logger.warning(f"  Insufficient text extracted from {pdf_path.name}")
        return []
    
    # Chunk if needed
    chunks = chunk_text(text, max_chunk_size=15000)
    logger.info(f"  Split into {len(chunks)} chunks")
    
    all_qa_pairs = []
    
    # Process each chunk (process all chunks for comprehensive coverage)
    for chunk_idx, chunk in enumerate(chunks):
        logger.info(f"  Processing chunk {chunk_idx + 1}/{len(chunks)}")
        
        qa_pairs = await generate_qa_pairs_from_text(
            text=chunk,
            source_filename=pdf_path.name,
            max_questions=max_questions_per_chunk
        )
        
        all_qa_pairs.extend(qa_pairs)
    
    # Format for CSV
    csv_rows = []
    for idx, qa in enumerate(all_qa_pairs):
        csv_rows.append({
            "Sno.": start_sno + idx,
            "Question (100 words)": qa.get("question", ""),
            "Answer (Max 2000 words)": qa.get("answer", ""),
            "Question Category (Refer Sheet 2)": qa.get("category", "GENERAL"),
            "Applicable to Pathways": "Breast Cancer",
            "Pathway Stage": "All Stages",
            "Source of Data (Preferable URL)": pdf_path.name,
            "Actual Excerpt from the Source Data": qa.get("excerpt", "")[:500],
            "Hospitals Applicable": "All",
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Author Name": author,
            "Reviewed By": "",
            "Expiry Date": ""
        })
    
    logger.info(f"  ✅ Generated {len(csv_rows)} Q&A pairs from {pdf_path.name}\n")
    return csv_rows


async def main():
    """Main processing function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Process PDF medical leaflets into Q&A pairs')
    parser.add_argument('--max-questions', '-q', type=int, default=15,
                        help='Maximum questions to generate per chunk (default: 15)')
    parser.add_argument('--sample', '-s', action='store_true',
                        help='Process only 3 sample files for testing')
    args = parser.parse_args()
    
    # Configuration
    DATA_DIR = Path(__file__).parent.parent / "data" / "sample" / "raw"
    OUTPUT_FILE = Path(__file__).parent.parent / "data" / "ProcessedQ&A_Generated.csv"
    
    # Get PDF files
    if args.sample:
        # Sample files for testing
        TEST_FILES = [
            "bcc17-chemotherapy-for-breast-cancer-web.pdf",
            "bcc20-tamoxifen-web.pdf",
            "bcc6-excercises-after-breast-cancer-surgery-web-pdf.pdf"
        ]
        TEST_FILES = [f for f in TEST_FILES if (DATA_DIR / f).exists()]
    else:
        # Get ALL PDF files
        TEST_FILES = sorted([f.name for f in DATA_DIR.glob("*.pdf")])
    
    logger.info("="*60)
    logger.info("PDF TO Q&A PROCESSING")
    logger.info("="*60)
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Output file: {OUTPUT_FILE}")
    logger.info(f"Processing {len(TEST_FILES)} files")
    logger.info(f"Max questions per chunk: {args.max_questions}")
    logger.info(f"Temperature: 0.0 (factual)")
    logger.info("="*60 + "\n")
    
    all_csv_rows = []
    current_sno = 1
    
    # Process each file
    for pdf_filename in TEST_FILES:
        pdf_path = DATA_DIR / pdf_filename
        
        if not pdf_path.exists():
            logger.warning(f"File not found: {pdf_filename}")
            continue
        
        csv_rows = await process_pdf_file(
            pdf_path, 
            start_sno=current_sno,
            max_questions_per_chunk=args.max_questions
        )
        all_csv_rows.extend(csv_rows)
        current_sno += len(csv_rows)
    
    # Write to CSV
    if all_csv_rows:
        logger.info("\n" + "="*60)
        logger.info("WRITING OUTPUT CSV")
        logger.info("="*60)
        
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS, delimiter='\t')
            writer.writeheader()
            writer.writerows(all_csv_rows)
        
        logger.info(f"✅ Written {len(all_csv_rows)} Q&A pairs to {OUTPUT_FILE}")
        logger.info(f"   Total files processed: {len(TEST_FILES)}")
        logger.info(f"   Average Q&A per file: {len(all_csv_rows)/len(TEST_FILES):.1f}")
        
        # Print summary by category
        category_counts = {}
        for row in all_csv_rows:
            cat = row["Question Category (Refer Sheet 2)"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        logger.info("\n   Category breakdown:")
        for cat, count in sorted(category_counts.items()):
            logger.info(f"     - {cat}: {count}")
    else:
        logger.error("No Q&A pairs generated!")
    
    logger.info("\n" + "="*60)
    logger.info("PROCESSING COMPLETE")
    logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())

