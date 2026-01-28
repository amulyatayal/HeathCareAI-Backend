#!/usr/bin/env python3
"""
List all OpenSearch indices with their document counts and sizes.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from config.aws import opensearch
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def list_all_indices():
    """List all OpenSearch indices."""
    try:
        client = opensearch()
        
        print("="*70)
        print("OPENSEARCH INDICES")
        print("="*70)
        
        # Use cat API with timeout
        try:
            indices = client.cat.indices(
                format='json',
                h='index,docs.count,store.size,health',
                request_timeout=30
            )
        except Exception as e:
            logger.error(f"Error calling cat.indices: {e}")
            print(f"\n❌ Error connecting to OpenSearch: {e}")
            print("\nTrying alternative method...")
            
            # Alternative: try to get indices one by one from known list
            known_indices = [
                "breast_cancer_knowledge",
                "breast_cancer_knowledge_qa",
                "kb_cancer_treatment",
                "nutrition_assistant",
                "forum_posts"
            ]
            
            print("\nChecking known indices:")
            for idx_name in known_indices:
                try:
                    if client.indices.exists(index=idx_name):
                        stats = client.indices.stats(index=idx_name)
                        doc_count = stats['indices'][idx_name]['total']['docs']['count']
                        print(f"  ✅ {idx_name}: {doc_count:,} documents")
                except:
                    print(f"  ❌ {idx_name}: Error checking")
            return
        
        # Filter out system indices
        user_indices = [idx for idx in indices if not idx.get('index', '').startswith('.')]
        
        if not user_indices:
            print("\nNo user indices found.")
            return
        
        print(f"\nTotal user indices: {len(user_indices)}\n")
        
        # Sort by document count
        user_indices.sort(key=lambda x: int(x.get('docs.count', 0) or 0), reverse=True)
        
        for idx in user_indices:
            index_name = idx.get('index', '')
            doc_count = idx.get('docs.count', '0')
            size = idx.get('store.size', '0b')
            health = idx.get('health', 'unknown')
            
            # Format display
            health_icon = {
                'green': '✅',
                'yellow': '⚠️',
                'red': '❌'
            }.get(health, '❓')
            
            print(f"{health_icon} {index_name}")
            print(f"   Documents: {int(doc_count):,}" if doc_count.isdigit() else f"   Documents: {doc_count}")
            print(f"   Size: {size}")
            print(f"   Health: {health}")
            print()
        
        # Summary
        total_docs = sum(int(idx.get('docs.count', 0) or 0) for idx in user_indices)
        print("="*70)
        print(f"Summary: {len(user_indices)} indices, {total_docs:,} total documents")
        print("="*70)
        
    except Exception as e:
        logger.error(f"Error listing indices: {e}")
        import traceback
        traceback.print_exc()
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    list_all_indices()
