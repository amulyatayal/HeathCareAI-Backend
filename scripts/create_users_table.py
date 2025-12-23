#!/usr/bin/env python3
"""
Create DynamoDB Users table for user profile storage.

Run with: python scripts/create_users_table.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError
from config import settings

# DynamoDB client with credentials from settings
dynamodb = boto3.client(
    'dynamodb',
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key
)


def create_users_table():
    """
    Create Users table for storing user profiles.
    
    Primary Key: user_id (Partition Key only)
    - Google users: user_id = JWT 'sub' claim
    - Guest users: user_id = 'guest_<uuid>'
    """
    table_name = "Users"
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'user_id', 'KeyType': 'HASH'},  # Partition key only
            ],
            AttributeDefinitions=[
                {'AttributeName': 'user_id', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',  # On-demand pricing
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


def wait_for_table():
    """Wait for table to become active."""
    table_name = "Users"
    
    print(f"\n⏳ Waiting for {table_name} to become active...")
    
    waiter = dynamodb.get_waiter('table_exists')
    
    try:
        waiter.wait(TableName=table_name)
        print(f"  ✓ {table_name} is active")
    except Exception as e:
        print(f"  ⚠ Could not verify {table_name}: {e}")


def main():
    print("=" * 60)
    print("🗄️  Creating DynamoDB Users Table")
    print(f"   Region: {settings.aws_region}")
    print("=" * 60)
    print()
    
    success = create_users_table()
    
    if success:
        wait_for_table()
        print()
        print("=" * 60)
        print("✅ Users table ready!")
        print()
        print("Table schema:")
        print("  - user_id (PK): Google 'sub' or 'guest_<uuid>'")
        print("  - email: User email (Google only)")
        print("  - name: Display name")
        print("  - picture: Avatar URL")
        print("  - auth_provider: 'google' or 'guest'")
        print("  - created_at: ISO timestamp")
        print("  - last_login: ISO timestamp")
        print("=" * 60)
    else:
        print()
        print("❌ Failed to create Users table. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
