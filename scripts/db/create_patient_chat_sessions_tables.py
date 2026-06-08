#!/usr/bin/env python3
"""
Create DynamoDB table for patient chat session memory.

Tables:
  - PatientChatSessions: PK session_id; GSI user_id-updated_at-index

Run with:  python scripts/db/create_patient_chat_sessions_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings

TABLE_NAME = "PatientChatSessions"
GSI_NAME = "user_id-updated_at-index"


def create_patient_chat_sessions_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)

    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "session_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "updated_at", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI_NAME,
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "updated_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "PatientChatSessions"},
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
    print("  Creating Patient Chat Sessions DynamoDB Table")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok = create_patient_chat_sessions_table()

    if ok:
        wait_for_table()
        print()
        print("=" * 60)
        print("  Patient chat sessions table ready!")
        print()
        print(f"  {TABLE_NAME}")
        print("    PK: session_id")
        print(f"    GSI: {GSI_NAME}")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
