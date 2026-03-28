#!/usr/bin/env python3
"""
Create DynamoDB table for Access Codes.

Table created:
  - AccessCodes: Maps short codes to clinician IDs for patient association

Run with:  python scripts/db/create_access_codes_table.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings


def create_access_codes_table():
    """
    Create the AccessCodes table.

    PK:  access_code (String)
    GSI: clinician_id-index (clinician_id PK)
    """
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "AccessCodes"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "access_code", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "access_code", "AttributeType": "S"},
                {"AttributeName": "clinician_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "clinician_id-index",
                    "KeySchema": [
                        {"AttributeName": "clinician_id", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "PatientClinicianAssociation"},
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


def wait_for_table():
    """Wait for table to become active."""
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "AccessCodes"
    print(f"  Waiting for {table_name}...")
    try:
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=table_name)
        print(f"    {table_name} is active")
    except Exception as e:
        print(f"    Could not verify {table_name}: {e}")


def main():
    print("=" * 60)
    print("  Creating AccessCodes DynamoDB Table")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok = create_access_codes_table()

    if ok:
        wait_for_table()
        print()
        print("=" * 60)
        print("  AccessCodes table ready!")
        print()
        print("  AccessCodes")
        print("    PK: access_code (String)")
        print("    GSI: clinician_id-index (clinician_id)")
        print("    Attributes: clinician_id, clinician_name, hospital_id,")
        print("                created_at, is_active")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
