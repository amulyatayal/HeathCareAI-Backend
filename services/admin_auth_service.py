"""
Admin Authentication Service
Handles clinician authentication with signed JWTs and bcrypt password hashing.

Admin auth is completely separate from the patient auth system.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from botocore.exceptions import ClientError

from config.aws import get_dynamodb_resource
from config.settings import settings

logger = logging.getLogger(__name__)


class AdminAuthService:
    """
    Manages admin user authentication against DynamoDB.
    
    Provides:
    - Password hashing and verification (bcrypt)
    - JWT creation and validation (HS256, signed)
    - Admin user lookup
    """
    
    TABLE_NAME = "AdminUsers"
    
    def __init__(self):
        self.dynamodb = get_dynamodb_resource()
        self.table = self.dynamodb.Table(self.TABLE_NAME)
    
    # ================================
    # Password Hashing
    # ================================
    
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    
    # ================================
    # JWT Management
    # ================================
    
    @staticmethod
    def create_token(user_id: str, email: str, role: str = "clinician") -> str:
        payload = {
            "sub": user_id,
            "email": email,
            "role": role,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=settings.admin_jwt_expiry_hours),
        }
        return jwt.encode(payload, settings.admin_jwt_secret, algorithm=settings.admin_jwt_algorithm)
    
    @staticmethod
    def verify_token(token: str) -> Optional[dict]:
        """
        Verify and decode an admin JWT.
        
        Returns the decoded payload if valid, None if expired or invalid.
        """
        try:
            return jwt.decode(
                token,
                settings.admin_jwt_secret,
                algorithms=[settings.admin_jwt_algorithm],
            )
        except jwt.ExpiredSignatureError:
            logger.warning("Admin token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid admin token: {e}")
            return None
    
    # ================================
    # User Operations
    # ================================
    
    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Look up an admin user by email (primary key)."""
        try:
            response = self.table.get_item(Key={"email": email})
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error looking up admin user {email}: {e}")
            raise
    
    def authenticate(self, email: str, password: str) -> Optional[dict]:
        """
        Authenticate a clinician.
        
        Returns a dict with token and user info on success, None on failure.
        """
        user = self.get_user_by_email(email)
        if not user:
            logger.warning(f"Admin login failed: no user with email {email}")
            return None
        
        if not self.verify_password(password, user["password_hash"]):
            logger.warning(f"Admin login failed: bad password for {email}")
            return None
        
        token = self.create_token(
            user_id=user["user_id"],
            email=user["email"],
            role=user.get("role", "clinician"),
        )
        
        logger.info(f"Admin login successful: {email}")
        
        return {
            "token": token,
            "user": {
                "id": user["user_id"],
                "name": user["name"],
                "email": user["email"],
                "role": user.get("role", "clinician"),
            },
        }
    
    def create_user(
        self,
        email: str,
        password: str,
        name: str,
        role: str = "clinician",
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Create a new admin user (used by seeding scripts).
        
        Returns the created user record (without password_hash).
        """
        import uuid
        
        uid = user_id or f"CLN-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow().isoformat()
        
        item = {
            "email": email,
            "user_id": uid,
            "name": name,
            "role": role,
            "password_hash": self.hash_password(password),
            "created_at": now,
            "updated_at": now,
        }
        
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(email)",
            )
            logger.info(f"Created admin user: {email} ({uid})")
            return {"user_id": uid, "email": email, "name": name, "role": role}
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"Admin user with email {email} already exists")
            raise


# ================================
# Singleton
# ================================

_service_instance: Optional[AdminAuthService] = None


def get_admin_auth_service() -> AdminAuthService:
    global _service_instance
    if _service_instance is None:
        _service_instance = AdminAuthService()
    return _service_instance
