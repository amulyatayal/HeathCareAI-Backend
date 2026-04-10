"""
Conversation Logger Service
Logs all chat conversations to DynamoDB for analytics and feedback
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.aws import get_dynamodb_table

logger = logging.getLogger(__name__)

# DynamoDB table name
CONVERSATIONS_TABLE = "ChatConversations"
USER_CREATED_GSI = "user_id-created_at-index"


class ConversationLogger:
    """Service to log conversations to DynamoDB"""
    
    def __init__(self, table_name: str = CONVERSATIONS_TABLE):
        self.table_name = table_name
        self._table = None
    
    def _get_table(self):
        """Lazy load DynamoDB table"""
        if self._table is None:
            self._table = get_dynamodb_table(self.table_name)
        return self._table
    
    async def log_conversation(
        self,
        session_id: str,
        user_id: Optional[str],
        question: str,
        answer: str,
        query_category: str,
        index_name: str,
        strict_mode: bool,
        has_sufficient_evidence: bool,
        confidence_score: float,
        response_time_ms: float,
        sources: List[Dict[str, Any]] = None,
        metadata: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Log a conversation to DynamoDB
        
        Returns:
            Dict with conversation_id and created_at, or None on failure
        """
        try:
            table = self._get_table()
            
            # Generate unique conversation ID
            conversation_id = f"{session_id}_{uuid.uuid4().hex[:8]}"
            
            # Current timestamp (as number for sort key)
            created_at = int(time.time() * 1000)  # milliseconds
            
            # Build the item
            item = {
                # Keys
                "conversation_id": conversation_id,
                "created_at": created_at,
                
                # Core data
                "session_id": session_id,
                "user_id": user_id or "anonymous",
                "question": question,
                "answer": answer,
                
                # Query metadata
                "query_category": query_category,
                "index_name": index_name,
                "strict_mode": strict_mode,
                "has_sufficient_evidence": has_sufficient_evidence,
                "confidence_score": Decimal(str(round(confidence_score, 4))),
                "response_time_ms": Decimal(str(round(response_time_ms, 2))),
                
                # Sources (simplified for storage)
                "sources_count": len(sources) if sources else 0,
                "source_documents": [s.get("title", "Unknown") for s in (sources or [])][:5],
                
                # Feedback (initialized as null)
                "feedback_rating": None,  # "thumbs_up" or "thumbs_down"
                "feedback_text": None,
                "feedback_timestamp": None,
                
                # Audit attributes
                "created_at_iso": datetime.utcnow().isoformat(),
                "updated_at": created_at,
                "updated_at_iso": datetime.utcnow().isoformat(),
                "version": 1
            }
            
            # Add optional metadata
            if metadata:
                item["metadata"] = metadata
            
            # Write to DynamoDB
            table.put_item(Item=item)
            
            logger.info(f"Logged conversation {conversation_id} to DynamoDB")
            return {
                "conversation_id": conversation_id,
                "created_at": created_at
            }
            
        except Exception as e:
            logger.error(f"Failed to log conversation to DynamoDB: {e}")
            # Don't raise - logging failure shouldn't break the chat
            return None
    
    async def update_feedback(
        self,
        conversation_id: str,
        created_at: int,
        feedback_rating: str,  # "thumbs_up" or "thumbs_down"
        feedback_text: Optional[str] = None
    ) -> bool:
        """
        Update feedback for a conversation
        
        Args:
            conversation_id: The conversation ID
            created_at: The sort key (timestamp in milliseconds)
            feedback_rating: "thumbs_up" or "thumbs_down"
            feedback_text: Optional detailed feedback text
        
        Returns:
            success: Whether the update was successful
        """
        try:
            table = self._get_table()
            
            feedback_timestamp = int(time.time() * 1000)
            
            update_expression = """
                SET feedback_rating = :rating,
                    feedback_text = :text,
                    feedback_timestamp = :ts,
                    updated_at = :updated,
                    updated_at_iso = :updated_iso,
                    version = version + :inc
            """
            
            table.update_item(
                Key={
                    "conversation_id": conversation_id,
                    "created_at": created_at
                },
                UpdateExpression=update_expression,
                ExpressionAttributeValues={
                    ":rating": feedback_rating,
                    ":text": feedback_text,
                    ":ts": feedback_timestamp,
                    ":updated": feedback_timestamp,
                    ":updated_iso": datetime.utcnow().isoformat(),
                    ":inc": 1
                }
            )
            
            logger.info(f"Updated feedback for conversation {conversation_id}: {feedback_rating}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update feedback: {e}")
            return False
    
    async def get_conversation(
        self,
        conversation_id: str,
        created_at: int
    ) -> Optional[Dict[str, Any]]:
        """Get a specific conversation by ID"""
        try:
            table = self._get_table()
            
            response = table.get_item(
                Key={
                    "conversation_id": conversation_id,
                    "created_at": created_at
                }
            )
            
            return response.get("Item")
            
        except Exception as e:
            logger.error(f"Failed to get conversation: {e}")
            return None
    
    async def get_user_conversations(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get conversations for a specific user (GSI query when available, else scan)."""
        try:
            table = self._get_table()
            try:
                response = table.query(
                    IndexName=USER_CREATED_GSI,
                    KeyConditionExpression=Key("user_id").eq(user_id),
                    ScanIndexForward=False,
                    Limit=limit,
                )
                return response.get("Items", [])
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code not in ("ValidationException", "ResourceNotFoundException"):
                    raise
                logger.debug(
                    "ChatConversations GSI %s unavailable (%s); falling back to scan",
                    USER_CREATED_GSI,
                    code,
                )
            response = table.scan(
                FilterExpression="user_id = :uid",
                ExpressionAttributeValues={":uid": user_id},
                Limit=limit,
            )
            return response.get("Items", [])
        except Exception as e:
            logger.error(f"Failed to get user conversations: {e}")
            return []


# Singleton instance
_conversation_logger = None


def get_conversation_logger() -> ConversationLogger:
    """Get or create the conversation logger singleton"""
    global _conversation_logger
    if _conversation_logger is None:
        _conversation_logger = ConversationLogger()
    return _conversation_logger

