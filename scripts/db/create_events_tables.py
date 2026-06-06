#!/usr/bin/env python3
"""
Create DynamoDB tables for clinician community events and patient RSVPs.

Tables:
  - AdminEvents:          PK event_id; GSI clinician_id-starts_at-index
  - PatientEventRsvps:    PK event_id, SK user_id

Run with:  python scripts/db/create_events_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings


def create_admin_events_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "AdminEvents"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "event_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "clinician_id", "AttributeType": "S"},
                {"AttributeName": "starts_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "clinician_id-starts_at-index",
                    "KeySchema": [
                        {"AttributeName": "clinician_id", "KeyType": "HASH"},
                        {"AttributeName": "starts_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "CommunityEvents"},
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


def create_patient_event_rsvps_table():
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PatientEventRsvps"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "event_id", "KeyType": "HASH"},
                {"AttributeName": "user_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "HealthcareAI"},
                {"Key": "Feature", "Value": "CommunityEvents"},
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
    for table_name in ["AdminEvents", "PatientEventRsvps"]:
        print(f"  Waiting for {table_name}...")
        try:
            waiter = dynamodb.get_waiter("table_exists")
            waiter.wait(TableName=table_name)
            print(f"    {table_name} is active")
        except Exception as e:
            print(f"    Could not verify {table_name}: {e}")


def main():
    print("=" * 60)
    print("  Creating Community Events DynamoDB Tables")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok1 = create_admin_events_table()
    ok2 = create_patient_event_rsvps_table()

    if ok1 and ok2:
        wait_for_tables()
        print()
        print("=" * 60)
        print("  Community events tables ready!")
        print()
        print("  AdminEvents")
        print("    PK: event_id")
        print("    GSI: clinician_id-starts_at-index")
        print()
        print("  PatientEventRsvps")
        print("    PK: event_id, SK: user_id")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
