#!/usr/bin/env python3
"""
Create DynamoDB tables for patient tracking features.

Tables created:
  - MoodEntries:     Mood tracking (user_id PK, timestamp SK)
  - SymptomEntries:  Symptom tracking (user_id PK, timestamp SK)
  - Appointments:    Appointment management (user_id PK, appointment_id SK, date GSI)

Run with:  python scripts/db/create_tracking_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings

TAGS = [
    {"Key": "Project", "Value": "HealthcareAI"},
    {"Key": "Feature", "Value": "PatientTracking"},
]


def create_table(dynamodb, table_name: str, key_schema: list,
                 attribute_defs: list, gsi: list = None) -> bool:
    try:
        params = {
            "TableName": table_name,
            "KeySchema": key_schema,
            "AttributeDefinitions": attribute_defs,
            "BillingMode": "PAY_PER_REQUEST",
            "Tags": TAGS,
        }
        if gsi:
            params["GlobalSecondaryIndexes"] = gsi

        dynamodb.create_table(**params)
        print(f"  Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  Table {table_name} already exists")
            return True
        print(f"  Failed to create {table_name}: {e}")
        return False


def create_mood_entries(dynamodb):
    return create_table(
        dynamodb,
        table_name="MoodEntries",
        key_schema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        attribute_defs=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
    )


def create_symptom_entries(dynamodb):
    return create_table(
        dynamodb,
        table_name="SymptomEntries",
        key_schema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        attribute_defs=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
    )


def create_appointments(dynamodb):
    return create_table(
        dynamodb,
        table_name="Appointments",
        key_schema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "appointment_id", "KeyType": "RANGE"},
        ],
        attribute_defs=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "appointment_id", "AttributeType": "S"},
            {"AttributeName": "date", "AttributeType": "S"},
        ],
        gsi=[
            {
                "IndexName": "user_date-index",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


def wait_for_tables(dynamodb, table_names):
    for name in table_names:
        print(f"  Waiting for {name}...")
        try:
            waiter = dynamodb.get_waiter("table_exists")
            waiter.wait(TableName=name)
            print(f"    {name} is active")
        except Exception as e:
            print(f"    Could not verify {name}: {e}")


def main():
    print("=" * 60)
    print("  Creating Patient Tracking DynamoDB Tables")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)

    ok1 = create_mood_entries(dynamodb)
    ok2 = create_symptom_entries(dynamodb)
    ok3 = create_appointments(dynamodb)

    if ok1 and ok2 and ok3:
        wait_for_tables(dynamodb, ["MoodEntries", "SymptomEntries", "Appointments"])
        print()
        print("=" * 60)
        print("  Patient Tracking tables ready!")
        print()
        print("  MoodEntries")
        print("    PK: user_id  SK: timestamp")
        print("    Attributes: entry_id, mood_score, note, emotions, triggers, quick_check")
        print()
        print("  SymptomEntries")
        print("    PK: user_id  SK: timestamp")
        print("    Attributes: entry_id, symptom_name, severity, notes")
        print()
        print("  Appointments")
        print("    PK: user_id  SK: appointment_id")
        print("    GSI: user_date-index (user_id, date)")
        print("    Attributes: title, date, time, location, reminder, status")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
