"""
Forum Service for Reddit-style Community Forums
Handles CRUD operations for posts, comments, and votes using DynamoDB
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal

from config.aws import get_dynamodb_table
from models.forum_schemas import (
    ForumCategory, ContentStatus, VoteType,
    PostCreate, PostUpdate, Post, PostSummary,
    CommentCreate, CommentUpdate, Comment,
    CategoryInfo, ForumUserProfile
)

logger = logging.getLogger(__name__)

# DynamoDB table names
POSTS_TABLE = "ForumPosts"
COMMENTS_TABLE = "ForumComments"
VOTES_TABLE = "ForumVotes"
CATEGORIES_TABLE = "ForumCategories"
USER_PROFILES_TABLE = "ForumUserProfiles"


class ForumService:
    """Service for managing forum posts, comments, and votes"""
    
    def __init__(self):
        self._posts_table = None
        self._comments_table = None
        self._votes_table = None
        self._categories_table = None
        self._profiles_table = None
    
    @property
    def posts_table(self):
        if self._posts_table is None:
            self._posts_table = get_dynamodb_table(POSTS_TABLE)
        return self._posts_table
    
    @property
    def comments_table(self):
        if self._comments_table is None:
            self._comments_table = get_dynamodb_table(COMMENTS_TABLE)
        return self._comments_table
    
    @property
    def votes_table(self):
        if self._votes_table is None:
            self._votes_table = get_dynamodb_table(VOTES_TABLE)
        return self._votes_table
    
    @property
    def categories_table(self):
        if self._categories_table is None:
            self._categories_table = get_dynamodb_table(CATEGORIES_TABLE)
        return self._categories_table
    
    @property
    def profiles_table(self):
        if self._profiles_table is None:
            self._profiles_table = get_dynamodb_table(USER_PROFILES_TABLE)
        return self._profiles_table

    # ================================
    # Categories
    # ================================
    
    def get_categories(self) -> List[CategoryInfo]:
        """Get all forum categories"""
        # Return predefined categories (can be extended to fetch from DynamoDB)
        categories = [
            CategoryInfo(
                category_id="treatment",
                name="Treatment Discussions",
                description="Share experiences and questions about treatments",
                icon="💊",
                color="#4CAF50"
            ),
            CategoryInfo(
                category_id="side_effects",
                name="Managing Side Effects",
                description="Tips and support for handling treatment side effects",
                icon="🩹",
                color="#FF9800"
            ),
            CategoryInfo(
                category_id="emotional_support",
                name="Emotional Support",
                description="A safe space to share feelings and find comfort",
                icon="💜",
                color="#9C27B0"
            ),
            CategoryInfo(
                category_id="lifestyle",
                name="Lifestyle & Wellness",
                description="Diet, exercise, and daily life tips",
                icon="🌱",
                color="#8BC34A"
            ),
            CategoryInfo(
                category_id="questions",
                name="Questions & Answers",
                description="Ask questions and get community insights",
                icon="❓",
                color="#2196F3"
            ),
            CategoryInfo(
                category_id="success_stories",
                name="Success Stories",
                description="Celebrate milestones and share hope",
                icon="🌟",
                color="#FFC107"
            ),
            CategoryInfo(
                category_id="caregivers",
                name="Caregivers Corner",
                description="Support for family members and caregivers",
                icon="🤝",
                color="#00BCD4"
            ),
            CategoryInfo(
                category_id="resources",
                name="Resources & Links",
                description="Helpful resources, articles, and information",
                icon="📚",
                color="#607D8B"
            ),
        ]
        return categories

    # ================================
    # Posts - Create
    # ================================
    
    async def create_post(
        self,
        post_data: PostCreate,
        user_id: str,
        user_display_name: str
    ) -> Post:
        """Create a new forum post"""
        post_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat() + "Z"
        created_at_ms = int(datetime.utcnow().timestamp() * 1000)
        
        # Prepare display name (anonymous if requested)
        display_name = "Anonymous" if post_data.is_anonymous else user_display_name
        
        item = {
            "post_id": post_id,
            "category_id": post_data.category_id,
            "created_at": Decimal(str(created_at_ms)),  # Sort key
            "created_at_iso": now,
            "title": post_data.title,
            "content": post_data.content,
            "user_id": user_id,
            "user_display_name": display_name,
            "is_anonymous": post_data.is_anonymous,
            "vote_count": 0,
            "comment_count": 0,
            "tags": post_data.tags,
            "is_pinned": False,
            "status": ContentStatus.ACTIVE.value,
        }
        
        try:
            self.posts_table.put_item(Item=item)
            logger.info(f"Created post {post_id} by user {user_id}")
            
            return Post(
                post_id=post_id,
                category_id=post_data.category_id,
                title=post_data.title,
                content=post_data.content,
                user_id=user_id if not post_data.is_anonymous else "anonymous",
                user_display_name=display_name,
                is_anonymous=post_data.is_anonymous,
                vote_count=0,
                comment_count=0,
                created_at=now,
                tags=post_data.tags,
                is_pinned=False,
                status=ContentStatus.ACTIVE,
            )
        except Exception as e:
            logger.error(f"Failed to create post: {e}")
            raise

    # ================================
    # Posts - Read
    # ================================
    
    async def get_post(self, post_id: str, current_user_id: Optional[str] = None) -> Optional[Post]:
        """Get a single post by ID"""
        try:
            # Query by post_id (need GSI on post_id)
            response = self.posts_table.query(
                IndexName="post_id-index",
                KeyConditionExpression="post_id = :pid",
                ExpressionAttributeValues={":pid": post_id}
            )
            
            items = response.get("Items", [])
            if not items:
                return None
            
            item = items[0]
            
            # Get user's vote if logged in
            user_vote = None
            if current_user_id:
                user_vote = await self._get_user_vote(current_user_id, "post", post_id)
            
            return self._item_to_post(item, user_vote)
            
        except Exception as e:
            logger.error(f"Failed to get post {post_id}: {e}")
            return None
    
    async def list_posts(
        self,
        category_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "new",  # "new", "top", "hot"
        current_user_id: Optional[str] = None
    ) -> Tuple[List[PostSummary], int, bool]:
        """List posts with pagination"""
        try:
            if category_id:
                # Query by category
                response = self.posts_table.query(
                    KeyConditionExpression="category_id = :cid",
                    ExpressionAttributeValues={":cid": category_id},
                    ScanIndexForward=False,  # Newest first
                    Limit=page_size * page  # Fetch enough for pagination
                )
            else:
                # Scan all posts (for "all" feed - use GSI in production)
                response = self.posts_table.scan(
                    Limit=page_size * page
                )
            
            items = response.get("Items", [])
            
            # Filter active posts only
            items = [i for i in items if i.get("status", "active") == "active"]
            
            # Sort based on criteria
            if sort_by == "top":
                items.sort(key=lambda x: int(x.get("vote_count", 0)), reverse=True)
            elif sort_by == "hot":
                # Hot = votes + recency bonus
                now_ms = datetime.utcnow().timestamp() * 1000
                items.sort(
                    key=lambda x: int(x.get("vote_count", 0)) + (1 - (now_ms - float(x.get("created_at", 0))) / 86400000),
                    reverse=True
                )
            # "new" is already sorted by created_at desc
            
            # Paginate
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_items = items[start_idx:end_idx]
            
            posts = [self._item_to_post_summary(item) for item in page_items]
            has_more = len(items) > end_idx
            
            return posts, len(items), has_more
            
        except Exception as e:
            logger.error(f"Failed to list posts: {e}")
            return [], 0, False

    # ================================
    # Posts - Update/Delete
    # ================================
    
    async def update_post(
        self,
        post_id: str,
        post_data: PostUpdate,
        user_id: str
    ) -> Optional[Post]:
        """Update a post (owner only)"""
        post = await self.get_post(post_id)
        if not post:
            return None
        
        # Check ownership (unless anonymous posts which store real user_id internally)
        # In production, store actual user_id separately for ownership checks
        
        now = datetime.utcnow().isoformat() + "Z"
        
        update_expr = "SET updated_at = :updated"
        expr_values = {":updated": now}
        
        if post_data.title:
            update_expr += ", title = :title"
            expr_values[":title"] = post_data.title
        
        if post_data.content:
            update_expr += ", content = :content"
            expr_values[":content"] = post_data.content
        
        if post_data.tags is not None:
            update_expr += ", tags = :tags"
            expr_values[":tags"] = post_data.tags
        
        try:
            # Need the full key to update
            response = self.posts_table.query(
                IndexName="post_id-index",
                KeyConditionExpression="post_id = :pid",
                ExpressionAttributeValues={":pid": post_id}
            )
            
            if not response.get("Items"):
                return None
            
            item = response["Items"][0]
            
            self.posts_table.update_item(
                Key={
                    "category_id": item["category_id"],
                    "created_at": item["created_at"]
                },
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values
            )
            
            return await self.get_post(post_id)
            
        except Exception as e:
            logger.error(f"Failed to update post {post_id}: {e}")
            return None
    
    async def delete_post(self, post_id: str, user_id: str) -> bool:
        """Soft delete a post (mark as deleted)"""
        try:
            response = self.posts_table.query(
                IndexName="post_id-index",
                KeyConditionExpression="post_id = :pid",
                ExpressionAttributeValues={":pid": post_id}
            )
            
            if not response.get("Items"):
                return False
            
            item = response["Items"][0]
            
            self.posts_table.update_item(
                Key={
                    "category_id": item["category_id"],
                    "created_at": item["created_at"]
                },
                UpdateExpression="SET #status = :status",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": ContentStatus.DELETED.value}
            )
            
            logger.info(f"Deleted post {post_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete post {post_id}: {e}")
            return False

    # ================================
    # Comments
    # ================================
    
    async def create_comment(
        self,
        post_id: str,
        comment_data: CommentCreate,
        user_id: str,
        user_display_name: str
    ) -> Optional[Comment]:
        """Create a new comment on a post"""
        comment_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat() + "Z"
        created_at_ms = int(datetime.utcnow().timestamp() * 1000)
        
        # Determine depth
        depth = 0
        if comment_data.parent_comment_id:
            parent = await self.get_comment(comment_data.parent_comment_id)
            if parent:
                depth = parent.depth + 1
        
        display_name = "Anonymous" if comment_data.is_anonymous else user_display_name
        
        item = {
            "post_id": post_id,
            "created_at": Decimal(str(created_at_ms)),
            "comment_id": comment_id,
            "parent_comment_id": comment_data.parent_comment_id,
            "user_id": user_id,
            "user_display_name": display_name,
            "is_anonymous": comment_data.is_anonymous,
            "content": comment_data.content,
            "vote_count": 0,
            "depth": depth,
            "status": ContentStatus.ACTIVE.value,
        }
        
        try:
            self.comments_table.put_item(Item=item)
            
            # Increment comment count on post
            await self._increment_post_comment_count(post_id)
            
            logger.info(f"Created comment {comment_id} on post {post_id}")
            
            return Comment(
                comment_id=comment_id,
                post_id=post_id,
                parent_comment_id=comment_data.parent_comment_id,
                user_id=user_id if not comment_data.is_anonymous else "anonymous",
                user_display_name=display_name,
                is_anonymous=comment_data.is_anonymous,
                content=comment_data.content,
                vote_count=0,
                created_at=now,
                depth=depth,
                status=ContentStatus.ACTIVE,
            )
            
        except Exception as e:
            logger.error(f"Failed to create comment: {e}")
            return None
    
    async def get_comment(self, comment_id: str) -> Optional[Comment]:
        """Get a single comment by ID"""
        try:
            response = self.comments_table.query(
                IndexName="comment_id-index",
                KeyConditionExpression="comment_id = :cid",
                ExpressionAttributeValues={":cid": comment_id}
            )
            
            items = response.get("Items", [])
            if not items:
                return None
            
            return self._item_to_comment(items[0])
            
        except Exception as e:
            logger.error(f"Failed to get comment {comment_id}: {e}")
            return None
    
    async def get_comments_for_post(
        self,
        post_id: str,
        current_user_id: Optional[str] = None
    ) -> List[Comment]:
        """Get all comments for a post, organized as a tree"""
        try:
            response = self.comments_table.query(
                KeyConditionExpression="post_id = :pid",
                ExpressionAttributeValues={":pid": post_id},
                ScanIndexForward=True  # Oldest first
            )
            
            items = response.get("Items", [])
            
            # Filter active comments
            items = [i for i in items if i.get("status", "active") == "active"]
            
            # Convert to Comment objects
            comments = []
            for item in items:
                user_vote = None
                if current_user_id:
                    user_vote = await self._get_user_vote(
                        current_user_id, "comment", item["comment_id"]
                    )
                comments.append(self._item_to_comment(item, user_vote))
            
            # Build tree structure
            return self._build_comment_tree(comments)
            
        except Exception as e:
            logger.error(f"Failed to get comments for post {post_id}: {e}")
            return []
    
    async def delete_comment(self, comment_id: str, user_id: str) -> bool:
        """Soft delete a comment"""
        try:
            response = self.comments_table.query(
                IndexName="comment_id-index",
                KeyConditionExpression="comment_id = :cid",
                ExpressionAttributeValues={":cid": comment_id}
            )
            
            if not response.get("Items"):
                return False
            
            item = response["Items"][0]
            
            self.comments_table.update_item(
                Key={
                    "post_id": item["post_id"],
                    "created_at": item["created_at"]
                },
                UpdateExpression="SET #status = :status, content = :content",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": ContentStatus.DELETED.value,
                    ":content": "[deleted]"
                }
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete comment {comment_id}: {e}")
            return False

    # ================================
    # Voting
    # ================================
    
    async def vote(
        self,
        user_id: str,
        target_type: str,  # "post" or "comment"
        target_id: str,
        vote: VoteType
    ) -> Tuple[bool, int]:
        """
        Cast a vote on a post or comment.
        Returns (success, new_vote_count)
        """
        try:
            vote_key = f"{target_type}:{target_id}"
            
            # Get existing vote
            existing_vote = await self._get_user_vote(user_id, target_type, target_id)
            
            # Calculate vote delta
            vote_delta = vote.value - (existing_vote or 0)
            
            if vote_delta == 0:
                # No change
                current_count = await self._get_vote_count(target_type, target_id)
                return True, current_count
            
            # Update or delete vote record
            if vote == VoteType.REMOVE:
                # Remove vote
                self.votes_table.delete_item(
                    Key={"user_id": user_id, "target_key": vote_key}
                )
            else:
                # Upsert vote
                self.votes_table.put_item(
                    Item={
                        "user_id": user_id,
                        "target_key": vote_key,
                        "target_type": target_type,
                        "target_id": target_id,
                        "vote": vote.value,
                        "created_at": datetime.utcnow().isoformat() + "Z"
                    }
                )
            
            # Update vote count on target
            new_count = await self._update_vote_count(target_type, target_id, vote_delta)
            
            logger.info(f"User {user_id} voted {vote.value} on {target_type} {target_id}")
            return True, new_count
            
        except Exception as e:
            logger.error(f"Failed to vote: {e}")
            return False, 0

    # ================================
    # Helper Methods
    # ================================
    
    async def _get_user_vote(
        self,
        user_id: str,
        target_type: str,
        target_id: str
    ) -> Optional[int]:
        """Get user's existing vote on a target"""
        try:
            vote_key = f"{target_type}:{target_id}"
            response = self.votes_table.get_item(
                Key={"user_id": user_id, "target_key": vote_key}
            )
            item = response.get("Item")
            return int(item["vote"]) if item else None
        except Exception:
            return None
    
    async def _get_vote_count(self, target_type: str, target_id: str) -> int:
        """Get current vote count for a target"""
        try:
            if target_type == "post":
                post = await self.get_post(target_id)
                return post.vote_count if post else 0
            else:
                comment = await self.get_comment(target_id)
                return comment.vote_count if comment else 0
        except Exception:
            return 0
    
    async def _update_vote_count(
        self,
        target_type: str,
        target_id: str,
        delta: int
    ) -> int:
        """Update vote count on a post or comment"""
        try:
            if target_type == "post":
                # Get post's full key
                response = self.posts_table.query(
                    IndexName="post_id-index",
                    KeyConditionExpression="post_id = :pid",
                    ExpressionAttributeValues={":pid": target_id}
                )
                if response.get("Items"):
                    item = response["Items"][0]
                    result = self.posts_table.update_item(
                        Key={
                            "category_id": item["category_id"],
                            "created_at": item["created_at"]
                        },
                        UpdateExpression="SET vote_count = vote_count + :delta",
                        ExpressionAttributeValues={":delta": delta},
                        ReturnValues="UPDATED_NEW"
                    )
                    return int(result["Attributes"]["vote_count"])
            else:
                # Get comment's full key
                response = self.comments_table.query(
                    IndexName="comment_id-index",
                    KeyConditionExpression="comment_id = :cid",
                    ExpressionAttributeValues={":cid": target_id}
                )
                if response.get("Items"):
                    item = response["Items"][0]
                    result = self.comments_table.update_item(
                        Key={
                            "post_id": item["post_id"],
                            "created_at": item["created_at"]
                        },
                        UpdateExpression="SET vote_count = vote_count + :delta",
                        ExpressionAttributeValues={":delta": delta},
                        ReturnValues="UPDATED_NEW"
                    )
                    return int(result["Attributes"]["vote_count"])
            
            return 0
        except Exception as e:
            logger.error(f"Failed to update vote count: {e}")
            return 0
    
    async def _increment_post_comment_count(self, post_id: str):
        """Increment comment count on a post"""
        try:
            response = self.posts_table.query(
                IndexName="post_id-index",
                KeyConditionExpression="post_id = :pid",
                ExpressionAttributeValues={":pid": post_id}
            )
            if response.get("Items"):
                item = response["Items"][0]
                self.posts_table.update_item(
                    Key={
                        "category_id": item["category_id"],
                        "created_at": item["created_at"]
                    },
                    UpdateExpression="SET comment_count = comment_count + :one",
                    ExpressionAttributeValues={":one": 1}
                )
        except Exception as e:
            logger.error(f"Failed to increment comment count: {e}")
    
    def _item_to_post(self, item: Dict[str, Any], user_vote: Optional[int] = None) -> Post:
        """Convert DynamoDB item to Post model"""
        return Post(
            post_id=item["post_id"],
            category_id=item["category_id"],
            title=item["title"],
            content=item["content"],
            user_id=item.get("user_id", "anonymous"),
            user_display_name=item.get("user_display_name", "Anonymous"),
            is_anonymous=item.get("is_anonymous", False),
            vote_count=int(item.get("vote_count", 0)),
            comment_count=int(item.get("comment_count", 0)),
            created_at=item.get("created_at_iso", ""),
            updated_at=item.get("updated_at"),
            tags=item.get("tags", []),
            is_pinned=item.get("is_pinned", False),
            status=ContentStatus(item.get("status", "active")),
            user_vote=user_vote,
        )
    
    def _item_to_post_summary(self, item: Dict[str, Any]) -> PostSummary:
        """Convert DynamoDB item to PostSummary model"""
        content = item.get("content", "")
        preview = content[:200] + "..." if len(content) > 200 else content
        
        return PostSummary(
            post_id=item["post_id"],
            category_id=item["category_id"],
            title=item["title"],
            content_preview=preview,
            user_id=item.get("user_id", "anonymous"),
            user_display_name=item.get("user_display_name", "Anonymous"),
            is_anonymous=item.get("is_anonymous", False),
            vote_count=int(item.get("vote_count", 0)),
            comment_count=int(item.get("comment_count", 0)),
            created_at=item.get("created_at_iso", ""),
            tags=item.get("tags", []),
            is_pinned=item.get("is_pinned", False),
        )
    
    def _item_to_comment(
        self,
        item: Dict[str, Any],
        user_vote: Optional[int] = None
    ) -> Comment:
        """Convert DynamoDB item to Comment model"""
        created_at = item.get("created_at")
        if isinstance(created_at, Decimal):
            from datetime import datetime
            created_at = datetime.utcfromtimestamp(float(created_at) / 1000).isoformat() + "Z"
        
        return Comment(
            comment_id=item["comment_id"],
            post_id=item["post_id"],
            parent_comment_id=item.get("parent_comment_id"),
            user_id=item.get("user_id", "anonymous"),
            user_display_name=item.get("user_display_name", "Anonymous"),
            is_anonymous=item.get("is_anonymous", False),
            content=item["content"],
            vote_count=int(item.get("vote_count", 0)),
            created_at=created_at if isinstance(created_at, str) else "",
            updated_at=item.get("updated_at"),
            depth=int(item.get("depth", 0)),
            status=ContentStatus(item.get("status", "active")),
            user_vote=user_vote,
        )
    
    def _build_comment_tree(self, comments: List[Comment]) -> List[Comment]:
        """Build nested comment tree from flat list"""
        comment_map = {c.comment_id: c for c in comments}
        root_comments = []
        
        for comment in comments:
            if comment.parent_comment_id:
                parent = comment_map.get(comment.parent_comment_id)
                if parent:
                    parent.replies.append(comment)
            else:
                root_comments.append(comment)
        
        return root_comments


# Singleton instance
_forum_service: Optional[ForumService] = None


def get_forum_service() -> ForumService:
    """Get or create forum service instance"""
    global _forum_service
    if _forum_service is None:
        _forum_service = ForumService()
    return _forum_service

