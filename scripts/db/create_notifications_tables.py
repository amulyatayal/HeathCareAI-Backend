#!/usr/bin/env python3
"""
Create DynamoDB tables for clinician notifications and per-patient read state.

Tables:
  - Notifications:        PK notification_id; GSI clinician_id-created_at-index
    Item attributes (application): created_at, updated_at (on soft-delete), is_deleted, ...
  - NotificationReads:    PK user_id, SK notification_id
    Item attributes (application): read_at (ISO UTC when marked read)

List APIs only return notifications from the last 90 days (see notification_service).

Run with:  python scripts/db/create_notifications_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings


def create_notifications_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "Notifications"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "notification_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "notification_id", "AttributeType": "S"},
                {"AttributeName": "clinician_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "clinician_id-created_at-index",
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
                {"Key": "Feature", "Value": "Notifications"},
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


def create_notification_reads_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "NotificationReads"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "notification_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "notification_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "Notifications"},
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
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    for table_name in ["Notifications", "NotificationReads"]:
        print(f"  Waiting for {table_name}...")
        try:
            waiter = dynamodb.get_waiter("table_exists")
            waiter.wait(TableName=table_name)
            print(f"    {table_name} is active")
        except Exception as e:
            print(f"    Could not verify {table_name}: {e}")


def main():
    print("=" * 60)
    print("  Creating Notifications DynamoDB Tables")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok1 = create_notifications_table()
    ok2 = create_notification_reads_table()

    if ok1 and ok2:
        wait_for_tables()
        print()
        print("=" * 60)
        print("  Notifications tables ready!")
        print()
        print("  Notifications")
        print("    PK: notification_id")
        print("    GSI: clinician_id-created_at-index (clinician_id, created_at)")
        print()
        print("  NotificationReads")
        print("    PK: user_id, SK: notification_id")
        print("    Items include read_at (set by application when patient marks read)")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
