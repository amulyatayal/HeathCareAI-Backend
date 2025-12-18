"""
Index PDF leaflets as chunks for RAG-based retrieval

This script:
1. Extracts text from PDFs with page numbers
2. Splits into semantic chunks (paragraphs/sections)
3. Indexes chunks with metadata (source, page, section)
4. Creates vector embeddings for hybrid search

The chatbot will retrieve these chunks and generate answers
with citations back to the source leaflets.
"""

import sys
import asyncio
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import hashlib

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

from config.aws import opensearch, bedrock
from config.settings import settings
from services.knowledge_base import EmbeddingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
CHUNK_SIZE = 800  # Target chunk size in characters
CHUNK_OVERLAP = 100  # Overlap between chunks for context continuity
MIN_CHUNK_SIZE = 100  # Minimum chunk size to index


def extract_pages_from_pdf(pdf_path: Path) -> List[Tuple[int, str]]:
    """
    Extract text from PDF with page numbers
    
    Returns:
        List of (page_number, page_text) tuples
    """
    pages = []
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            
            for page_num, page in enumerate(pdf_reader.pages, start=1):
                text = page.extract_text()
                if text and text.strip():
                    # Clean up the text
                    text = re.sub(r'\s+', ' ', text).strip()
                    pages.append((page_num, text))
                    
        logger.info(f"  Extracted {len(pages)} pages from {pdf_path.name}")
        return pages
        
    except Exception as e:
        logger.error(f"Error extracting PDF {pdf_path.name}: {e}")
        return []


def detect_section_header(text: str) -> Optional[str]:
    """
    Try to detect section headers in text
    Common patterns: ALL CAPS, numbered sections, bold markers
    """
    # Look for common section patterns
    patterns = [
        r'^([A-Z][A-Z\s]{5,50})$',  # ALL CAPS lines
        r'^(\d+\.?\s+[A-Z][a-zA-Z\s]+)$',  # Numbered sections
        r'^(What|How|When|Why|Where|Who|Can|Should|Will|Is|Are|Do|Does)\s',  # Question headers
    ]
    
    lines = text.split('\n')
    for line in lines[:3]:  # Check first 3 lines
        line = line.strip()
        for pattern in patterns:
            if re.match(pattern, line):
                return line[:100]  # Truncate long headers
    return None


def chunk_text_with_metadata(
    pages: List[Tuple[int, str]],
    source_filename: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP
) -> List[Dict]:
    """
    Split pages into semantic chunks with metadata
    
    Returns:
        List of chunk dictionaries with:
        - content: The chunk text
        - source_file: PDF filename
        - page_start: Starting page number
        - page_end: Ending page number
        - section: Detected section header (if any)
        - chunk_index: Position in document
    """
    chunks = []
    current_chunk = ""
    current_pages = []
    current_section = None
    chunk_index = 0
    
    for page_num, page_text in pages:
        # Detect section header
        section = detect_section_header(page_text)
        if section:
            current_section = section
        
        # Split page into paragraphs
        paragraphs = re.split(r'\n\s*\n|\.\s{2,}', page_text)
        
        for para in paragraphs:
            para = para.strip()
            if not para or len(para) < 20:
                continue
            
            # Check if adding this paragraph exceeds chunk size
            if len(current_chunk) + len(para) > chunk_size and current_chunk:
                # Save current chunk
                if len(current_chunk) >= MIN_CHUNK_SIZE:
                    chunks.append({
                        "content": current_chunk.strip(),
                        "source_file": source_filename,
                        "page_start": min(current_pages) if current_pages else page_num,
                        "page_end": max(current_pages) if current_pages else page_num,
                        "section": current_section,
                        "chunk_index": chunk_index
                    })
                    chunk_index += 1
                
                # Start new chunk with overlap
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else ""
                current_chunk = overlap_text + " " + para
                current_pages = [page_num]
            else:
                # Add to current chunk
                current_chunk += " " + para
                if page_num not in current_pages:
                    current_pages.append(page_num)
    
    # Don't forget the last chunk
    if current_chunk and len(current_chunk) >= MIN_CHUNK_SIZE:
        chunks.append({
            "content": current_chunk.strip(),
            "source_file": source_filename,
            "page_start": min(current_pages) if current_pages else 1,
            "page_end": max(current_pages) if current_pages else 1,
            "section": current_section,
            "chunk_index": chunk_index
        })
    
    return chunks


def get_chunk_index_mapping() -> Dict:
    """
    Get OpenSearch index mapping for PDF chunks
    Optimized for hybrid search (BM25 + vector)
    """
    return {
        "settings": {
            "index": {
                "number_of_shards": 2,
                "number_of_replicas": 1,
                "knn": True
            }
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "content": {
                    "type": "text",
                    "analyzer": "standard"
                },
                "source_file": {"type": "keyword"},
                "page_start": {"type": "integer"},
                "page_end": {"type": "integer"},
                "section": {"type": "text"},
                "chunk_index": {"type": "integer"},
                "created_at": {"type": "date"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": settings.kb_embedding_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "faiss",
                        "parameters": {
                            "ef_construction": 512,
                            "m": 16
                        }
                    }
                }
            }
        }
    }


async def create_index(client, index_name: str) -> bool:
    """Create OpenSearch index for chunks"""
    try:
        # Check if index exists
        if client.indices.exists(index=index_name):
            logger.info(f"Index {index_name} already exists")
            return True
        
        # Create index with mapping
        mapping = get_chunk_index_mapping()
        client.indices.create(index=index_name, body=mapping)
        logger.info(f"Created index: {index_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating index: {e}")
        return False


async def index_chunks(
    client,
    embedding_service: EmbeddingService,
    chunks: List[Dict],
    index_name: str,
    dry_run: bool = False
) -> Tuple[int, int]:
    """
    Index chunks with embeddings
    
    Returns:
        Tuple of (successful_count, error_count)
    """
    successful = 0
    errors = 0
    
    for i, chunk in enumerate(chunks):
        try:
            # Generate unique chunk ID
            chunk_id = hashlib.md5(
                f"{chunk['source_file']}:{chunk['page_start']}:{chunk['chunk_index']}".encode()
            ).hexdigest()[:16]
            
            if dry_run:
                logger.info(f"  [DRY RUN] Would index chunk {i+1}: {chunk['content'][:50]}...")
                successful += 1
                continue
            
            # Create embedding
            embedding = embedding_service.create_embedding(chunk['content'])
            
            if not embedding:
                logger.warning(f"  Failed to create embedding for chunk {i+1}")
                errors += 1
                continue
            
            # Prepare document
            doc = {
                "chunk_id": chunk_id,
                "content": chunk['content'],
                "source_file": chunk['source_file'],
                "page_start": chunk['page_start'],
                "page_end": chunk['page_end'],
                "section": chunk.get('section'),
                "chunk_index": chunk['chunk_index'],
                "created_at": datetime.utcnow().isoformat(),
                "embedding": embedding
            }
            
            # Index document
            client.index(index=index_name, body=doc)
            successful += 1
            
            if (i + 1) % 50 == 0:
                logger.info(f"  Progress: {i+1}/{len(chunks)} chunks indexed")
                
        except Exception as e:
            logger.error(f"  Error indexing chunk {i+1}: {e}")
            errors += 1
    
    return successful, errors


async def process_pdf(
    pdf_path: Path,
    client,
    embedding_service: EmbeddingService,
    index_name: str,
    dry_run: bool = False
) -> Tuple[int, int]:
    """
    Process a single PDF file and index its chunks
    
    Returns:
        Tuple of (successful_count, error_count)
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {pdf_path.name}")
    logger.info(f"{'='*60}")
    
    # Extract pages
    pages = extract_pages_from_pdf(pdf_path)
    if not pages:
        logger.warning(f"  No content extracted from {pdf_path.name}")
        return 0, 0
    
    # Chunk the content
    chunks = chunk_text_with_metadata(pages, pdf_path.name)
    logger.info(f"  Created {len(chunks)} chunks")
    
    # Index chunks
    successful, errors = await index_chunks(
        client, embedding_service, chunks, index_name, dry_run
    )
    
    logger.info(f"  ✓ Indexed: {successful}, ✗ Errors: {errors}")
    return successful, errors


async def main():
    """Main processing function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Index PDF chunks for RAG retrieval')
    parser.add_argument('--index', '-i',
                        default='breast_cancer_knowledge',
                        help='Target OpenSearch index name')
    parser.add_argument('--data-dir', '-d',
                        default='data/sample/raw',
                        help='Directory containing PDF files')
    parser.add_argument('--dry-run',
                        action='store_true',
                        help='Parse and show what would be indexed')
    parser.add_argument('--sample', '-s',
                        action='store_true',
                        help='Process only 3 sample files for testing')
    parser.add_argument('--chunk-size', '-c',
                        type=int,
                        default=CHUNK_SIZE,
                        help=f'Target chunk size in characters (default: {CHUNK_SIZE})')
    
    args = parser.parse_args()
    
    # Configuration
    script_dir = Path(__file__).parent.parent
    data_dir = script_dir / args.data_dir
    index_name = args.index
    
    # Get PDF files
    pdf_files = sorted(list(data_dir.glob("*.pdf")))
    
    if args.sample:
        pdf_files = pdf_files[:3]
    
    logger.info("="*60)
    logger.info("PDF CHUNK INDEXING FOR RAG")
    logger.info("="*60)
    logger.info(f"Data directory: {data_dir}")
    logger.info(f"Target index: {index_name}")
    logger.info(f"PDF files: {len(pdf_files)}")
    logger.info(f"Chunk size: {args.chunk_size} chars")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("="*60)
    
    if not pdf_files:
        logger.error(f"No PDF files found in {data_dir}")
        return
    
    # Initialize clients
    client = opensearch()
    embedding_service = EmbeddingService()
    
    # Create index
    if not args.dry_run:
        if not await create_index(client, index_name):
            logger.error("Failed to create index. Aborting.")
            return
    
    # Process each PDF
    total_successful = 0
    total_errors = 0
    
    for pdf_path in pdf_files:
        successful, errors = await process_pdf(
            pdf_path,
            client,
            embedding_service,
            index_name,
            args.dry_run
        )
        total_successful += successful
        total_errors += errors
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("INDEXING COMPLETE")
    logger.info("="*60)
    logger.info(f"  PDF files processed: {len(pdf_files)}")
    logger.info(f"  Chunks indexed: {total_successful}")
    logger.info(f"  Errors: {total_errors}")
    logger.info(f"  Index: {index_name}")
    if args.dry_run:
        logger.info("  Mode: DRY RUN (no actual indexing)")
    logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())

