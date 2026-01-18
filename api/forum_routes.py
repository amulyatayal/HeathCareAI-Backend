"""
Forum API Routes for Reddit-style Community Forums
Provides endpoints for posts, comments, voting, and categories
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Header, Request

from models.forum_schemas import (
    PostCreate, PostUpdate, Post, PostSummary, PostListResponse, PostDetailResponse,
    CommentCreate, CommentUpdate, Comment,
    VoteRequest, VoteResponse, VoteType,
    CategoryInfo, ReportRequest, ReportResponse
)
from services.forum_service import get_forum_service

logger = logging.getLogger(__name__)

# ================================
# Forum Router
# ================================

forum_router = APIRouter(prefix="/forum", tags=["Community Forum"])


def _extract_user_id(
    authorization: Optional[str] = None,
    x_user_id: Optional[str] = None
) -> tuple[str, str]:
    """
    Extract user_id and display_name from headers.
    Returns (user_id, display_name)
    """
    if authorization and authorization.startswith("Bearer "):
        try:
            import jwt
            token = authorization.replace("Bearer ", "")
            decoded = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded.get("sub") or decoded.get("email") or "authenticated_user"
            display_name = decoded.get("name") or decoded.get("email", "User").split("@")[0]
            return user_id, display_name
        except Exception:
            return "authenticated_user", "User"
    elif x_user_id:
        # Guest user
        return x_user_id, f"Guest_{x_user_id[-4:]}"
    else:
        return "anonymous", "Anonymous"


# ================================
# Categories
# ================================

@forum_router.get("/categories", response_model=list[CategoryInfo])
async def get_categories():
    """
    Get all available forum categories.
    
    Returns a list of categories with names, descriptions, and icons.
    """
    service = get_forum_service()
    return service.get_categories()


# ================================
# Posts - CRUD
# ================================

@forum_router.post("/posts", response_model=Post)
async def create_post(
    post_data: PostCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Create a new forum post.
    
    Requires authentication via Authorization header (JWT) or X-User-ID header.
    
    - **title**: Post title (5-200 characters)
    - **content**: Post content (10-10000 characters)
    - **category_id**: One of the available categories
    - **tags**: Optional list of tags (max 5)
    - **is_anonymous**: If true, username will be hidden
    """
    user_id, display_name = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(
            status_code=401,
            detail="Authentication required to create posts"
        )
    
    service = get_forum_service()
    
    try:
        post = await service.create_post(post_data, user_id, display_name)
        return post
    except Exception as e:
        logger.error(f"Failed to create post: {e}")
        raise HTTPException(status_code=500, detail="Failed to create post")


@forum_router.get("/posts", response_model=PostListResponse)
async def list_posts(
    category: Optional[str] = Query(None, description="Filter by category ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=50, description="Items per page"),
    sort: str = Query("new", pattern="^(new|top|hot)$", description="Sort order"),
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    List forum posts with pagination and sorting.
    
    - **category**: Filter by category ID (optional)
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 50)
    - **sort**: Sort order - "new" (default), "top", or "hot"
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    current_user = user_id if user_id != "anonymous" else None
    
    service = get_forum_service()
    
    try:
        posts, total, has_more = await service.list_posts(
            category_id=category,
            page=page,
            page_size=page_size,
            sort_by=sort,
            current_user_id=current_user
        )
        
        return PostListResponse(
            posts=posts,
            total_count=total,
            page=page,
            page_size=page_size,
            has_more=has_more
        )
    except Exception as e:
        logger.error(f"Failed to list posts: {e}")
        raise HTTPException(status_code=500, detail="Failed to list posts")


@forum_router.get("/posts/{post_id}", response_model=PostDetailResponse)
async def get_post(
    post_id: str,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Get a single post with all its comments.
    
    Returns the full post content and a nested tree of comments.
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    current_user = user_id if user_id != "anonymous" else None
    
    service = get_forum_service()
    
    try:
        post = await service.get_post(post_id, current_user)
        
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        
        comments = await service.get_comments_for_post(post_id, current_user)
        
        return PostDetailResponse(
            post=post,
            comments=comments,
            comment_count=post.comment_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get post {post_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get post")


@forum_router.put("/posts/{post_id}", response_model=Post)
async def update_post(
    post_id: str,
    post_data: PostUpdate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Update a post (owner only).
    
    Only the post owner can update their post.
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = get_forum_service()
    
    try:
        post = await service.update_post(post_id, post_data, user_id)
        
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        
        return post
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update post {post_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update post")


@forum_router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Delete a post (owner only).
    
    Posts are soft-deleted (marked as deleted but not removed).
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = get_forum_service()
    
    try:
        success = await service.delete_post(post_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Post not found")
        
        return {"message": "Post deleted successfully", "post_id": post_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete post {post_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete post")


# ================================
# Comments
# ================================

@forum_router.post("/posts/{post_id}/comments", response_model=Comment)
async def create_comment(
    post_id: str,
    comment_data: CommentCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Add a comment to a post.
    
    - **content**: Comment text (1-5000 characters)
    - **parent_comment_id**: Optional - for nested replies
    - **is_anonymous**: If true, username will be hidden
    """
    user_id, display_name = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = get_forum_service()
    
    # Verify post exists
    post = await service.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    try:
        comment = await service.create_comment(
            post_id, comment_data, user_id, display_name
        )
        
        if not comment:
            raise HTTPException(status_code=500, detail="Failed to create comment")
        
        return comment
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create comment: {e}")
        raise HTTPException(status_code=500, detail="Failed to create comment")


@forum_router.get("/posts/{post_id}/comments", response_model=list[Comment])
async def get_comments(
    post_id: str,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Get all comments for a post.
    
    Returns a nested tree structure of comments.
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    current_user = user_id if user_id != "anonymous" else None
    
    service = get_forum_service()
    
    try:
        comments = await service.get_comments_for_post(post_id, current_user)
        return comments
    except Exception as e:
        logger.error(f"Failed to get comments for post {post_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get comments")


@forum_router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: str,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Delete a comment (owner only).
    
    Comments are soft-deleted (content replaced with "[deleted]").
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = get_forum_service()
    
    try:
        success = await service.delete_comment(comment_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Comment not found")
        
        return {"message": "Comment deleted successfully", "comment_id": comment_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete comment {comment_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete comment")


# ================================
# Voting
# ================================

@forum_router.post("/vote", response_model=VoteResponse)
async def vote(
    vote_data: VoteRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Vote on a post or comment.
    
    - **target_type**: "post" or "comment"
    - **target_id**: The ID of the post or comment
    - **vote**: 1 (upvote), -1 (downvote), or 0 (remove vote)
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required to vote")
    
    service = get_forum_service()
    
    try:
        success, new_count = await service.vote(
            user_id=user_id,
            target_type=vote_data.target_type,
            target_id=vote_data.target_id,
            vote=vote_data.vote
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to record vote")
        
        # Get user's current vote
        user_vote = await service._get_user_vote(
            user_id, vote_data.target_type, vote_data.target_id
        )
        
        return VoteResponse(
            success=True,
            target_type=vote_data.target_type,
            target_id=vote_data.target_id,
            new_vote_count=new_count,
            user_vote=user_vote or 0
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to vote: {e}")
        raise HTTPException(status_code=500, detail="Failed to record vote")


# ================================
# Reporting (placeholder)
# ================================

@forum_router.post("/report", response_model=ReportResponse)
async def report_content(
    report_data: ReportRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Report a post or comment for moderation review.
    
    - **target_type**: "post" or "comment"
    - **target_id**: The ID of the content to report
    - **reason**: Reason for reporting (10-500 characters)
    """
    user_id, _ = _extract_user_id(authorization, x_user_id)
    
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # For MVP, just log the report
    import uuid
    report_id = str(uuid.uuid4())[:8]
    
    logger.warning(
        f"Content reported: {report_data.target_type} {report_data.target_id} "
        f"by {user_id} - Reason: {report_data.reason}"
    )
    
    return ReportResponse(
        success=True,
        message="Thank you for your report. Our team will review it.",
        report_id=report_id
    )

