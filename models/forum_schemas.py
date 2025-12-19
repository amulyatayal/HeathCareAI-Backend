"""
Forum Schemas for Reddit-style Community Forums
Pydantic models for posts, comments, votes, and categories
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum


# ================================
# Enums
# ================================

class ForumCategory(str, Enum):
    """Predefined forum categories for healthcare discussions"""
    TREATMENT = "treatment"
    SIDE_EFFECTS = "side_effects"
    EMOTIONAL_SUPPORT = "emotional_support"
    LIFESTYLE = "lifestyle"
    QUESTIONS = "questions"
    SUCCESS_STORIES = "success_stories"
    CAREGIVERS = "caregivers"
    RESOURCES = "resources"


class VoteType(int, Enum):
    """Vote types: upvote, downvote, or remove"""
    UPVOTE = 1
    DOWNVOTE = -1
    REMOVE = 0


class ContentStatus(str, Enum):
    """Content moderation status"""
    ACTIVE = "active"
    HIDDEN = "hidden"  # Hidden by moderator
    DELETED = "deleted"  # Deleted by user
    FLAGGED = "flagged"  # Flagged for review


# ================================
# Category Schemas
# ================================

class CategoryInfo(BaseModel):
    """Forum category information"""
    category_id: str
    name: str
    description: str
    icon: Optional[str] = None
    post_count: int = 0
    color: Optional[str] = None  # For UI theming


# ================================
# Post Schemas
# ================================

class PostCreate(BaseModel):
    """Request model for creating a new post"""
    title: str = Field(..., min_length=5, max_length=200)
    content: str = Field(..., min_length=10, max_length=10000)
    category_id: str
    tags: List[str] = Field(default_factory=list, max_length=5)
    is_anonymous: bool = False


class PostUpdate(BaseModel):
    """Request model for updating a post"""
    title: Optional[str] = Field(None, min_length=5, max_length=200)
    content: Optional[str] = Field(None, min_length=10, max_length=10000)
    tags: Optional[List[str]] = Field(None, max_length=5)


class PostSummary(BaseModel):
    """Lightweight post summary for list views"""
    post_id: str
    category_id: str
    title: str
    content_preview: str  # First 200 chars
    user_id: str
    user_display_name: str
    is_anonymous: bool = False
    vote_count: int = 0
    comment_count: int = 0
    created_at: str
    tags: List[str] = []
    is_pinned: bool = False


class Post(BaseModel):
    """Full post model with all details"""
    post_id: str
    category_id: str
    title: str
    content: str
    user_id: str
    user_display_name: str
    is_anonymous: bool = False
    vote_count: int = 0
    comment_count: int = 0
    created_at: str
    updated_at: Optional[str] = None
    tags: List[str] = []
    is_pinned: bool = False
    status: ContentStatus = ContentStatus.ACTIVE
    user_vote: Optional[int] = None  # Current user's vote on this post


class PostListResponse(BaseModel):
    """Response for paginated post list"""
    posts: List[PostSummary]
    total_count: int
    page: int
    page_size: int
    has_more: bool


class PostDetailResponse(BaseModel):
    """Response for single post with comments"""
    post: Post
    comments: List["Comment"] = []
    comment_count: int = 0


# ================================
# Comment Schemas
# ================================

class CommentCreate(BaseModel):
    """Request model for creating a comment"""
    content: str = Field(..., min_length=1, max_length=5000)
    parent_comment_id: Optional[str] = None  # For nested replies
    is_anonymous: bool = False


class CommentUpdate(BaseModel):
    """Request model for updating a comment"""
    content: str = Field(..., min_length=1, max_length=5000)


class Comment(BaseModel):
    """Comment model"""
    comment_id: str
    post_id: str
    parent_comment_id: Optional[str] = None
    user_id: str
    user_display_name: str
    is_anonymous: bool = False
    content: str
    vote_count: int = 0
    created_at: str
    updated_at: Optional[str] = None
    depth: int = 0  # Nesting level (0 = top-level, 1 = reply, etc.)
    status: ContentStatus = ContentStatus.ACTIVE
    user_vote: Optional[int] = None  # Current user's vote
    replies: List["Comment"] = []  # Nested replies


# ================================
# Vote Schemas
# ================================

class VoteRequest(BaseModel):
    """Request model for voting"""
    target_type: str = Field(..., pattern="^(post|comment)$")
    target_id: str
    vote: VoteType


class VoteResponse(BaseModel):
    """Response after voting"""
    success: bool
    target_type: str
    target_id: str
    new_vote_count: int
    user_vote: int


# ================================
# Moderation Schemas
# ================================

class ReportRequest(BaseModel):
    """Request to report content"""
    target_type: str = Field(..., pattern="^(post|comment)$")
    target_id: str
    reason: str = Field(..., min_length=10, max_length=500)


class ReportResponse(BaseModel):
    """Response after reporting"""
    success: bool
    message: str
    report_id: str


# Update forward references for nested models
Comment.model_rebuild()
PostDetailResponse.model_rebuild()

