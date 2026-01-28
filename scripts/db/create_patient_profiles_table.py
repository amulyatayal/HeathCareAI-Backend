#!/usr/bin/env python3
"""
Create DynamoDB table for Patient Profiles.

This table stores patient profile information including:
- Current treatment stage (user-provided)
- Onboarding completion status
- Explicit medical journey data

Run with: python scripts/db/create_patient_profiles_table.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings


def create_patient_profiles_table():
    """
    Create PatientProfiles table.
    
    Primary Key: user_id (HASH) - Firebase UID for authenticated users
    
    Stores:
    - current_stage: Patient's current treatment stage
    - onboarding_completed: Whether onboarding wizard was completed
    - explicit_data: User-provided medical journey information
    - stage_history: List of stage changes over time
    """
    dynamodb = boto3.client('dynamodb', region_name=settings.aws_region)
    table_name = "PatientProfiles"
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'user_id', 'KeyType': 'HASH'},  # Partition key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'user_id', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',  # On-demand pricing
            Tags=[
                {'Key': 'Project', 'Value': 'HealthcareAI'},
                {'Key': 'Feature', 'Value': 'PatientStageClassification'},
            ]
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
    dynamodb = boto3.client('dynamodb', region_name=settings.aws_region)
    table_name = "PatientProfiles"
    
    print(f"\n⏳ Waiting for {table_name} to become active...")
    
    try:
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=table_name)
        print(f"  ✓ {table_name} is active")
        return True
    except Exception as e:
        print(f"  ⚠ Could not verify {table_name}: {e}")
        return False


def main():
    print("=" * 60)
    print("🗄️  Creating PatientProfiles DynamoDB Table")
    print(f"   Region: {settings.aws_region}")
    print("=" * 60)
    print()
    
    if create_patient_profiles_table():
        wait_for_table()
        print()
        print("=" * 60)
        print("✅ PatientProfiles table ready!")
        print()
        print("Table schema:")
        print("  - Primary Key: user_id (String) - Firebase UID")
        print()
        print("Stored attributes:")
        print("  - current_stage: Patient's treatment stage")
        print("  - stage_updated_at: When stage was last updated")
        print("  - onboarding_completed: Boolean")
        print("  - onboarding_completed_at: Timestamp")
        print("  - explicit_data: User-provided journey details (Map)")
        print("  - stage_history: List of stage changes")
        print("  - created_at, updated_at: Timestamps")
        print("=" * 60)
    else:
        print()
        print("❌ Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
