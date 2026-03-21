#!/usr/bin/env python3
"""
Create DynamoDB tables for the Admin Portal.

Tables created:
  - AdminUsers:        Clinician accounts (email PK)
  - PathwayResources:  Educational resources (resource_id PK, clinician_id GSI)

Also seeds one default admin user for development.

Run with:  python scripts/db/create_admin_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings


def create_admin_users_table():
    """Create the AdminUsers table (email as PK)."""
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "AdminUsers"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "email", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "AdminPortal"},
            ],
        )
        print(f"  Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  Table {table_name} already exists")
            return True
        print(f"  Failed to create {table_name}: {e}")
        return False


def create_pathway_resources_table():
    """
    Create the PathwayResources table.
    
    PK:  resource_id
    GSI: clinician_id-index (clinician_id PK, created_at SK)
    """
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PathwayResources"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "resource_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "resource_id", "AttributeType": "S"},
                {"AttributeName": "clinician_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "clinician_id-index",
                    "KeySchema": [
                        {"AttributeName": "clinician_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "AdminPortal"},
            ],
        )
        print(f"  Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  Table {table_name} already exists")
            return True
        print(f"  Failed to create {table_name}: {e}")
        return False


def wait_for_tables():
    """Wait for both tables to become active."""
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    for table_name in ["AdminUsers", "PathwayResources"]:
        print(f"  Waiting for {table_name}...")
        try:
            waiter = dynamodb.get_waiter("table_exists")
            waiter.wait(TableName=table_name)
            print(f"    {table_name} is active")
        except Exception as e:
            print(f"    Could not verify {table_name}: {e}")


def seed_default_admin():
    """Create a default admin user for development."""
    from services.admin_auth_service import get_admin_auth_service

    service = get_admin_auth_service()
    email = "admin@hospital.nhs.uk"

    try:
        user = service.create_user(
            email=email,
            password="admin123",
            name="Dev Admin",
            role="clinician",
            user_id="CLN-DEV001",
        )
        print(f"  Seeded admin user: {user['email']} (password: admin123)")
    except ValueError:
        print(f"  Admin user {email} already exists — skipping seed")
    except Exception as e:
        print(f"  Could not seed admin user: {e}")


def main():
    print("=" * 60)
    print("  Creating Admin Portal DynamoDB Tables")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok1 = create_admin_users_table()
    ok2 = create_pathway_resources_table()

    if ok1 and ok2:
        wait_for_tables()
        print()
        seed_default_admin()
        print()
        print("=" * 60)
        print("  Admin Portal tables ready!")
        print()
        print("  AdminUsers")
        print("    PK: email (String)")
        print("    Attributes: user_id, name, role, password_hash, created_at")
        print()
        print("  PathwayResources")
        print("    PK: resource_id (String)")
        print("    GSI: clinician_id-index (clinician_id, created_at)")
        print("    Attributes: clinician_name, pathway_stage_ids, description,")
        print("                intents, resources, is_deleted, created_at, updated_at")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
