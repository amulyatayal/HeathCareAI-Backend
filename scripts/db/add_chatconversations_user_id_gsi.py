#!/usr/bin/env python3
"""
Add GSI user_id-created_at-index to existing ChatConversations table.

Items already include user_id (string) and created_at (number, ms). This GSI supports
efficient export and account deletion by patient.

Safe to run once; if the index already exists, the script exits successfully.

Run with:  python scripts/db/add_chatconversations_user_id_gsi.py

Requires: boto3 credentials and dynamodb:UpdateTable on ChatConversations.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings

TABLE_NAME = "ChatConversations"
INDEX_NAME = "user_id-created_at-index"


def main():
    client = boto3.client("dynamodb", region_name=settings.aws_region)
    print(f"Checking {TABLE_NAME} in {settings.aws_region}...")

    try:
        desc = client.describe_table(TableName=TABLE_NAME)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            print(f"  Table {TABLE_NAME} not found. Create it first (e.g. create_forum_tables.py).")
            sys.exit(1)
        raise

    for idx in desc["Table"].get("GlobalSecondaryIndexes") or []:
        if idx["IndexName"] == INDEX_NAME:
            print(f"  GSI {INDEX_NAME} already exists — nothing to do.")
            return

    print(f"  Adding GSI {INDEX_NAME}...")

    try:
        client.update_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "conversation_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "N"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexUpdates=[
                {
                    "Create": {
                        "IndexName": INDEX_NAME,
                        "KeySchema": [
                            {"AttributeName": "user_id", "KeyType": "HASH"},
                            {"AttributeName": "created_at", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                }
            ],
        )
        print(f"  Create index {INDEX_NAME} submitted; waiting for ACTIVE...")
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)
        desc = client.describe_table(TableName=TABLE_NAME)
        indexes = desc["Table"].get("GlobalSecondaryIndexes") or []
        for idx in indexes:
            if idx["IndexName"] == INDEX_NAME:
                print(f"  Index {INDEX_NAME} status: {idx['IndexStatus']}")
                return
        print("  Warning: index not found in describe_table output yet.")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ResourceInUseException":
            print("  Table busy (another update in progress). Retry later.")
            sys.exit(2)
        if code == "ValidationException":
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                print(f"  Index {INDEX_NAME} already exists — nothing to do.")
                return
            print(f"  ValidationException: {e}")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
