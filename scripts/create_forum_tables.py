#!/usr/bin/env python3
"""
Create DynamoDB tables for the Community Forum feature.

Tables created:
- ForumPosts: Stores all forum posts
- ForumComments: Stores comments on posts
- ForumVotes: Tracks user votes on posts and comments
- ForumUserProfiles: User karma and stats (optional)

Run with: python scripts/create_forum_tables.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError
from config import settings

# DynamoDB client
dynamodb = boto3.client('dynamodb', region_name=settings.aws_region)


def create_forum_posts_table():
    """
    Create ForumPosts table.
    
    Primary Key: category_id (PK) + created_at (SK)
    GSI: post_id-index for looking up posts by ID
    """
    table_name = "ForumPosts"
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'category_id', 'KeyType': 'HASH'},  # Partition key
                {'AttributeName': 'created_at', 'KeyType': 'RANGE'},  # Sort key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'category_id', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'N'},
                {'AttributeName': 'post_id', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'post_id-index',
                    'KeySchema': [
                        {'AttributeName': 'post_id', 'KeyType': 'HASH'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        print(f"✓ Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"⚠ Table {table_name} already exists")
            return True
        else:
            print(f"✗ Failed to create {table_name}: {e}")
            return False


def create_forum_comments_table():
    """
    Create ForumComments table.
    
    Primary Key: post_id (PK) + created_at (SK)
    GSI: comment_id-index for looking up comments by ID
    """
    table_name = "ForumComments"
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'post_id', 'KeyType': 'HASH'},  # Partition key
                {'AttributeName': 'created_at', 'KeyType': 'RANGE'},  # Sort key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'post_id', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'N'},
                {'AttributeName': 'comment_id', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'comment_id-index',
                    'KeySchema': [
                        {'AttributeName': 'comment_id', 'KeyType': 'HASH'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        print(f"✓ Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"⚠ Table {table_name} already exists")
            return True
        else:
            print(f"✗ Failed to create {table_name}: {e}")
            return False


def create_forum_votes_table():
    """
    Create ForumVotes table.
    
    Primary Key: user_id (PK) + target_key (SK)
    target_key format: "post:abc123" or "comment:xyz789"
    """
    table_name = "ForumVotes"
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'user_id', 'KeyType': 'HASH'},  # Partition key
                {'AttributeName': 'target_key', 'KeyType': 'RANGE'},  # Sort key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'user_id', 'AttributeType': 'S'},
                {'AttributeName': 'target_key', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        print(f"✓ Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"⚠ Table {table_name} already exists")
            return True
        else:
            print(f"✗ Failed to create {table_name}: {e}")
            return False


def create_chat_conversations_table():
    """
    Create ChatConversations table (for conversation logging).
    
    Primary Key: conversation_id (PK) + created_at (SK)
    """
    table_name = "ChatConversations"
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'conversation_id', 'KeyType': 'HASH'},  # Partition key
                {'AttributeName': 'created_at', 'KeyType': 'RANGE'},  # Sort key (Number - ms timestamp)
            ],
            AttributeDefinitions=[
                {'AttributeName': 'conversation_id', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'N'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        print(f"✓ Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"⚠ Table {table_name} already exists")
            return True
        else:
            print(f"✗ Failed to create {table_name}: {e}")
            return False


def wait_for_tables():
    """Wait for all tables to become active."""
    tables = [
        "ForumPosts",
        "ForumComments", 
        "ForumVotes",
        "ChatConversations"
    ]
    
    print("\n⏳ Waiting for tables to become active...")
    
    waiter = dynamodb.get_waiter('table_exists')
    
    for table_name in tables:
        try:
            waiter.wait(TableName=table_name)
            print(f"  ✓ {table_name} is active")
        except Exception as e:
            print(f"  ⚠ Could not verify {table_name}: {e}")


def main():
    print("=" * 60)
    print("🗄️  Creating DynamoDB Tables for Community Forum")
    print(f"   Region: {settings.aws_region}")
    print("=" * 60)
    print()
    
    # Create all tables
    success = True
    success &= create_forum_posts_table()
    success &= create_forum_comments_table()
    success &= create_forum_votes_table()
    success &= create_chat_conversations_table()
    
    if success:
        wait_for_tables()
        print()
        print("=" * 60)
        print("✅ All tables created successfully!")
        print()
        print("Tables created:")
        print("  - ForumPosts (category_id + created_at)")
        print("  - ForumComments (post_id + created_at)")
        print("  - ForumVotes (user_id + target_key)")
        print("  - ChatConversations (conversation_id + created_at)")
        print("=" * 60)
    else:
        print()
        print("❌ Some tables failed to create. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

