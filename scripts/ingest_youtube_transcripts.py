"""
Ingest YouTube transcript chunks into OpenSearch with embeddings
Reads JSONL file with YouTube transcript data and indexes into youtube_transcripts index
"""

import sys
import json
import asyncio
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from services.knowledge_base import get_knowledge_base, create_index_if_not_exists, EmbeddingService
from config.aws import opensearch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# YouTube KB index name
YOUTUBE_KB_NAME = "youtube_transcripts"


def read_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
    """Read JSONL file and parse YouTube transcript chunks"""
    chunks = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                chunk_data = json.loads(line)
                chunks.append(chunk_data)
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON on line {line_num}: {e}")
                continue
    
    return chunks


def get_youtube_index_mapping() -> Dict[str, Any]:
    """Get OpenSearch index mapping for YouTube transcripts with video metadata"""
    from config import settings
    
    mappings = {
        "properties": {
            "document_id": {"type": "keyword"},
            "content": {"type": "text", "analyzer": "standard"},
            "video_id": {"type": "keyword"},
            "video_title": {"type": "text", "analyzer": "standard"},
            "channel": {"type": "keyword"},
            "video_url": {"type": "keyword"},
            "timestamped_url": {"type": "keyword"},
            "start_seconds": {"type": "float"},
            "end_seconds": {"type": "float"},
            "start_timestamp": {"type": "keyword"},
            "end_timestamp": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
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
    
    settings_dict = {
        "index": {
            "number_of_shards": 2,
            "number_of_replicas": 1,
            "knn": True
        }
    }
    
    return {
        "settings": settings_dict,
        "mappings": mappings
    }


async def ingest_youtube_chunks(chunks: List[Dict[str, Any]], dry_run: bool = False, index_name: str = None):
    """Ingest YouTube transcript chunks into OpenSearch with embeddings"""
    index_name = index_name or YOUTUBE_KB_NAME
    
    if not dry_run:
        logger.info(f"Checking/creating OpenSearch index '{index_name}' with vector support...")
        client = opensearch()
        
        if not client.indices.exists(index=index_name):
            mapping = get_youtube_index_mapping()
            client.indices.create(index=index_name, body=mapping)
            logger.info(f"Created index: {index_name} (vectors=enabled)")
        else:
            logger.info(f"Index already exists: {index_name}")
    
    # Initialize embedding service
    embedding_service = EmbeddingService()
    
    # Get OpenSearch client
    client = opensearch()
    
    success_count = 0
    error_count = 0
    start_time = time.time()
    
    logger.info(f"\nStarting ingestion of {len(chunks)} YouTube transcript chunks...")
    logger.info(f"Dry run: {dry_run}\n")
    
    for i, chunk in enumerate(chunks):
        try:
            # Extract video metadata
            video_id = chunk.get("video_id", "")
            video_title = chunk.get("video_title", "Unknown Video")
            channel = chunk.get("channel", "Unknown Channel")
            video_url = chunk.get("video_url", "")
            timestamped_url = chunk.get("timestamped_url", "")
            start_seconds = chunk.get("start_seconds", 0.0)
            end_seconds = chunk.get("end_seconds", 0.0)
            start_timestamp = chunk.get("start_timestamp", "")
            end_timestamp = chunk.get("end_timestamp", "")
            chunk_index = chunk.get("chunk_index", 0)
            text = chunk.get("text", chunk.get("content", ""))
            
            if not text:
                logger.warning(f"Skipping chunk {i+1}: No text content")
                error_count += 1
                continue
            
            # Create document ID
            doc_id = f"youtube_{video_id}_{chunk_index}"
            
            # Prepare document body
            doc_body = {
                "document_id": doc_id,
                "content": text,
                "video_id": video_id,
                "video_title": video_title,
                "channel": channel,
                "video_url": video_url,
                "timestamped_url": timestamped_url,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "chunk_index": chunk_index,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            
            if dry_run:
                logger.info(
                    f"[DRY RUN] Would add chunk {i+1}: "
                    f"Video: {video_title[:40]}... | "
                    f"Timestamp: {start_timestamp} | "
                    f"Text: {text[:50]}..."
                )
                success_count += 1
            else:
                # Create embedding
                text_for_embedding = f"{video_title}. {text}"[:8000]  # Titan limit
                embedding = embedding_service.create_embedding(text_for_embedding)
                
                if not embedding:
                    logger.error(f"Failed to create embedding for chunk {i+1}")
                    error_count += 1
                    continue
                
                doc_body["embedding"] = embedding
                
                # Index document
                response = client.index(
                    index=index_name,
                    body=doc_body
                )
                
                if (i + 1) % 50 == 0:
                    logger.info(f"Progress: {i+1}/{len(chunks)} ({(i+1)/len(chunks)*100:.1f}%)")
                
                success_count += 1
                
        except Exception as e:
            logger.error(f"Error adding chunk {i+1}: {e}")
            error_count += 1
    
    elapsed = time.time() - start_time
    
    logger.info(f"\n{'='*60}")
    logger.info(f"INGESTION COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  Successful: {success_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info(f"  Total: {len(chunks)}")
    logger.info(f"  Time: {elapsed:.1f}s ({elapsed/len(chunks):.2f}s per chunk)")
    logger.info(f"  Vectors: Enabled (Hybrid Search)")
    logger.info(f"  Index: {index_name}")
    
    # Video statistics
    if chunks:
        unique_videos = len(set(ch.get("video_id", "") for ch in chunks if ch.get("video_id")))
        logger.info(f"\n  Unique videos: {unique_videos}")
        
        # Show sample videos
        seen_videos = set()
        sample_videos = []
        for chunk in chunks:
            video_id = chunk.get("video_id")
            if video_id and video_id not in seen_videos:
                seen_videos.add(video_id)
                sample_videos.append({
                    "id": video_id,
                    "title": chunk.get("video_title", "Unknown")[:50]
                })
                if len(sample_videos) >= 5:
                    break
        
        if sample_videos:
            logger.info(f"  Sample videos:")
            for vid in sample_videos:
                logger.info(f"    - {vid['id']}: {vid['title']}...")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Ingest YouTube transcript chunks into OpenSearch')
    parser.add_argument('--file', '-f',
                        required=True,
                        help='Path to JSONL file with YouTube transcript chunks')
    parser.add_argument('--index', '-i',
                        default=YOUTUBE_KB_NAME,
                        help=f'OpenSearch index name (default: {YOUTUBE_KB_NAME})')
    parser.add_argument('--dry-run', '-d',
                        action='store_true',
                        help='Parse and show what would be uploaded without actually uploading')
    
    args = parser.parse_args()
    
    # Get absolute path
    file_path = Path(args.file)
    if not file_path.is_absolute():
        script_dir = Path(__file__).parent.parent
        file_path = script_dir / args.file
    
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return
    
    logger.info("="*60)
    logger.info("YOUTUBE TRANSCRIPT INGESTION")
    logger.info("="*60)
    logger.info(f"Input file: {file_path}")
    logger.info(f"Target index: {args.index}")
    logger.info(f"Using hybrid search (vector + keyword)")
    logger.info("="*60 + "\n")
    
    # Read JSONL
    logger.info(f"Reading JSONL file...")
    chunks = read_jsonl_file(file_path)
    logger.info(f"Found {len(chunks)} transcript chunks\n")
    
    if not chunks:
        logger.error("No chunks found in JSONL file!")
        return
    
    # Show sample
    logger.info("Sample chunks:")
    for i, chunk in enumerate(chunks[:3], 1):
        logger.info(f"  Chunk {i}:")
        logger.info(f"    Video: {chunk.get('video_title', 'N/A')[:50]}...")
        logger.info(f"    Video ID: {chunk.get('video_id', 'N/A')}")
        logger.info(f"    Channel: {chunk.get('channel', 'N/A')}")
        logger.info(f"    Timestamp: {chunk.get('start_timestamp', 'N/A')}")
        logger.info(f"    Text: {chunk.get('text', chunk.get('content', 'N/A'))[:60]}...")
        logger.info("")
    
    # Ingest
    await ingest_youtube_chunks(chunks, dry_run=args.dry_run, index_name=args.index)


if __name__ == "__main__":
    asyncio.run(main())
