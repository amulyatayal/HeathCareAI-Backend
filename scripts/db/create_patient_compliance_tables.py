#!/usr/bin/env python3
"""
Create DynamoDB tables for patient GDPR/DPDPA compliance (consent + audit).

Tables:
  - PatientComplianceAuditEvents:  PK event_id; GSI user_id-occurred_at-index
    Append-only compliance events (PutItem only from application code).
  - PatientConsents:                 PK user_id, SK consent_type (cookies | data)
    Current consent row per type; withdrawn_at set on withdrawal (GET returns null).

Run with:  python scripts/db/create_patient_compliance_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from botocore.exceptions import ClientError
from config import settings

TAGS = [
    {"Key": "Project", "Value": "HealthcareAI"},
    {"Key": "Feature", "Value": "PatientCompliance"},
]


def create_patient_compliance_audit_events_table() -> bool:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PatientComplianceAuditEvents"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "event_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "occurred_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "user_id-occurred_at-index",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "occurred_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=TAGS,
        )
        print(f"  Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  Table {table_name} already exists")
            return True
        print(f"  Failed to create {table_name}: {e}")
        return False


def create_patient_consents_table() -> bool:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PatientConsents"

    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "consent_type", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "consent_type", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=TAGS,
        )
        print(f"  Created table: {table_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  Table {table_name} already exists")
            return True
        print(f"  Failed to create {table_name}: {e}")
        return False


def wait_for_tables(table_names: list) -> None:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
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
    print("  Creating Patient Compliance DynamoDB Tables")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    print()

    ok1 = create_patient_compliance_audit_events_table()
    ok2 = create_patient_consents_table()

    if ok1 and ok2:
        wait_for_tables(["PatientComplianceAuditEvents", "PatientConsents"])
        print()
        print("=" * 60)
        print("  Patient compliance tables ready!")
        print()
        print("  PatientComplianceAuditEvents")
        print("    PK: event_id")
        print("    GSI: user_id-occurred_at-index")
        print()
        print("  PatientConsents")
        print("    PK: user_id  SK: consent_type (cookies | data)")
        print("=" * 60)
    else:
        print()
        print("  Table creation failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
