#!/usr/bin/env python3
"""
Create DynamoDB tables for patient compliance phase 3:
  - PatientGrievances:   PK grievance_id; GSI user_id-created_at-index
  - PatientNominees:     PK user_id (one nominee record per patient, DPDPA India)
  - PatientDataShares:   PK share_id; GSI token_hash-index; GSI user_id-created_at-index

Run with:  python scripts/db/create_patient_compliance_phase3_tables.py
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


def create_patient_grievances_table() -> bool:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PatientGrievances"
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "grievance_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "grievance_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "user_id-created_at-index",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
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


def create_patient_nominees_table() -> bool:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PatientNominees"
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
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


def create_patient_data_shares_table() -> bool:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    table_name = "PatientDataShares"
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "share_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "share_id", "AttributeType": "S"},
                {"AttributeName": "token_hash", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "token_hash-index",
                    "KeySchema": [{"AttributeName": "token_hash", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "user_id-created_at-index",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
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


def wait_for_tables(names: list) -> None:
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
    for name in names:
        print(f"  Waiting for {name}...")
        try:
            dynamodb.get_waiter("table_exists").wait(TableName=name)
            print(f"    {name} is active")
        except Exception as e:
            print(f"    Could not verify {name}: {e}")


def main():
    print("=" * 60)
    print("  Patient compliance phase 3 DynamoDB tables")
    print(f"  Region: {settings.aws_region}")
    print("=" * 60)
    ok1 = create_patient_grievances_table()
    ok2 = create_patient_nominees_table()
    ok3 = create_patient_data_shares_table()
    if ok1 and ok2 and ok3:
        wait_for_tables(["PatientGrievances", "PatientNominees", "PatientDataShares"])
        print("=" * 60)
        print("  Done.")
        print("=" * 60)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
