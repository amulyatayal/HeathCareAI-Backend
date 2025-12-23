"""
User Service for DynamoDB operations.
Follows the pattern established in forum_service.py
"""

import logging
from datetime import datetime
from typing import Optional
import boto3
from botocore.exceptions import ClientError

from config import settings
from models.user import UserCreate, UserResponse

logger = logging.getLogger(__name__)

# DynamoDB table name
USERS_TABLE = "Users"


class UserService:
    """Service for managing user profiles in DynamoDB"""
    
    def __init__(self):
        self._dynamodb = None
        self._table = None
    
    @property
    def dynamodb(self):
        """Lazy load DynamoDB resource"""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource(
                'dynamodb',
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key
            )
        return self._dynamodb
    
    @property
    def table(self):
        """Lazy load Users table"""
        if self._table is None:
            self._table = self.dynamodb.Table(USERS_TABLE)
        return self._table
    
    async def sync_user(
        self,
        user_id: str,
        name: str,
        email: Optional[str],
        picture: Optional[str],
        auth_provider: str
    ) -> tuple[dict, bool]:
        """
        Create or update user on login.
        
        Returns:
            Tuple of (user_dict, is_new_user)
        """
        now = datetime.utcnow().isoformat()
        
        try:
            # Check if user exists
            existing = await self.get_user(user_id)
            is_new_user = existing is None
            
            if is_new_user:
                # Create new user
                item = {
                    'user_id': user_id,
                    'name': name,
                    'email': email,
                    'picture': picture,
                    'auth_provider': auth_provider,
                    'created_at': now,
                    'last_login': now
                }
                # Remove None values
                item = {k: v for k, v in item.items() if v is not None}
                
                self.table.put_item(Item=item)
                logger.info(f"Created new user: {user_id}")
            else:
                # Update existing user
                update_expr = "SET #name = :name, last_login = :last_login"
                expr_names = {'#name': 'name'}
                expr_values = {':name': name, ':last_login': now}
                
                # Update picture if provided
                if picture:
                    update_expr += ", picture = :picture"
                    expr_values[':picture'] = picture
                
                self.table.update_item(
                    Key={'user_id': user_id},
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames=expr_names,
                    ExpressionAttributeValues=expr_values
                )
                logger.info(f"Updated existing user: {user_id}")
                item = {**existing, 'name': name, 'last_login': now}
                if picture:
                    item['picture'] = picture
            
            return item, is_new_user
            
        except ClientError as e:
            logger.error(f"Error syncing user {user_id}: {e}")
            raise
    
    async def get_user(self, user_id: str) -> Optional[dict]:
        """Get user by ID"""
        try:
            response = self.table.get_item(Key={'user_id': user_id})
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Error getting user {user_id}: {e}")
            raise
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete user account"""
        try:
            self.table.delete_item(Key={'user_id': user_id})
            logger.info(f"Deleted user: {user_id}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            raise


# Singleton instance
_user_service: Optional[UserService] = None


def get_user_service() -> UserService:
    """Get user service singleton"""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
        logger.info("Initialized UserService")
    return _user_service
