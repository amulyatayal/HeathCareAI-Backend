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

from datetime import datetime

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


def seed_default_admins_and_access_codes():
    """Create default admin users and fixed access codes for development."""
    from services.admin_auth_service import get_admin_auth_service

    service = get_admin_auth_service()
    admins_to_seed = [
        {
            "email": "admin@hospital.nhs.uk",
            "password": "admin123",
            "name": "Dev Admin",
            "role": "clinician",
            "user_id": "CLN-DEV001",
            "hospital_id": "dev",
        },
        {
            "email": "admin@barts.com",
            "password": "admin123",
            "name": "Barts Admin",
            "role": "clinician",
            "user_id": "CLN-BARTS001",
            "hospital_id": "barts",
        },
        {
            "email": "admin@uhnm.com",
            "password": "admin123",
            "name": "UHNM Admin",
            "role": "clinician",
            "user_id": "CLN-UHNM001",
            "hospital_id": "uhnm",
        },
        {
            "email": "admin@futuredreams.com",
            "password": "admin123",
            "name": "Future Dreams Admin",
            "role": "clinician",
            "user_id": "CLN-FD001",
            "hospital_id": "futuredreams",
        },
    ]

    for admin in admins_to_seed:
        try:
            user = service.create_user(
                email=admin["email"],
                password=admin["password"],
                name=admin["name"],
                role=admin["role"],
                user_id=admin["user_id"],
                hospital_id=admin["hospital_id"],
            )
            print(f"  Seeded admin user: {user['email']} (password: admin123)")
        except ValueError:
            print(f"  Admin user {admin['email']} already exists — skipping seed")
        except Exception as e:
            print(f"  Could not seed admin user {admin['email']}: {e}")

    # Fixed deterministic access codes requested for hospitals.
    access_codes_to_seed = [
        {
            "access_code": "barts-2026-X1Y1".upper(),
            "clinician_id": "CLN-BARTS001",
            "clinician_name": "Barts Admin",
            "hospital_id": "barts",
        },
        {
            "access_code": "uhnm-2026-X1Y1".upper(),
            "clinician_id": "CLN-UHNM001",
            "clinician_name": "UHNM Admin",
            "hospital_id": "uhnm",
        },
        {
            "access_code": "futuredreams-2026-X1Y1".upper(),
            "clinician_id": "CLN-FD001",
            "clinician_name": "Future Dreams Admin",
            "hospital_id": "futuredreams",
        },
    ]

    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    access_codes_table = dynamodb.Table("AccessCodes")
    now = datetime.utcnow().isoformat() + "Z"

    for row in access_codes_to_seed:
        try:
            access_codes_table.put_item(
                Item={
                    "access_code": row["access_code"],
                    "clinician_id": row["clinician_id"],
                    "clinician_name": row["clinician_name"],
                    "hospital_id": row["hospital_id"],
                    "created_at": now,
                    "is_active": True,
                },
                ConditionExpression="attribute_not_exists(access_code)",
            )
            print(f"  Seeded access code: {row['access_code']}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                print(f"  Access code {row['access_code']} already exists — skipping seed")
            elif e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                print("  AccessCodes table missing — skipping access code seed")
                break
            else:
                print(f"  Could not seed access code {row['access_code']}: {e}")


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
        seed_default_admins_and_access_codes()
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
