#!/usr/bin/env python3
"""
Create DynamoDB table for clinician-managed care team roster.

Tables:
  - AdminClinicalTeam:  PK team_member_id; GSI clinician_id-index

Run with:  python scripts/db/create_clinical_team_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings

TABLE_NAME = "AdminClinicalTeam"


def create_admin_clinical_team_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)

    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "team_member_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "team_member_id", "AttributeType": "S"},
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
                {"Key": "Feature", "Value": "ClinicalTeam"},
            ],
        )
        print(f"  Created table: {TABLE_NAME}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  Table {TABLE_NAME} already exists")
            return True
        print(f"  Failed to create {TABLE_NAME}: {e}")
        return False


def wait_for_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    print(f"  Waiting for {TABLE_NAME}...")
    try:
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)
        print(f"    {TABLE_NAME} is active")
    except Exception as e:
        print(f"    Could not verify {TABLE_NAME}: {e}")


def main():
    print("=" * 60)
    print("  Creating Clinical Team DynamoDB Table")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok = create_admin_clinical_team_table()

    if ok:
        wait_for_table()
        print()
        print("=" * 60)
        print("  Clinical team table ready!")
        print()
        print(f"  {TABLE_NAME}")
        print("    PK: team_member_id")
        print("    GSI: clinician_id-index")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
