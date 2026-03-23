"""
Pathway Resource Service
DynamoDB CRUD for clinician-managed educational resources.

Each resource is an educational item (PDF, video, link) associated
with one or more treatment pathway stages.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)


class PathwayResourceService:
    """
    Manages pathway resources in DynamoDB.
    
    Table: PathwayResources
    PK: resource_id (UUID string)
    GSI: clinician_id-index (clinician_id PK, created_at SK)
    """
    
    TABLE_NAME = "PathwayResources"
    
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(self.TABLE_NAME)
    
    # ================================
    # Create
    # ================================
    
    def create_resource(self, data: dict) -> dict:
        """
        Create a new pathway resource.
        
        Args:
            data: Dict with clinician_name, clinician_id, pathway_stage_ids,
                  description, intents, resources.
        
        Returns:
            The created resource dict with id, created_at, updated_at.
        """
        now = datetime.utcnow().isoformat() + "Z"
        resource_id = str(uuid.uuid4())
        
        item = {
            "resource_id": resource_id,
            "clinician_name": data["clinician_name"],
            "clinician_id": data["clinician_id"],
            "pathway_stage_ids": data.get("pathway_stage_ids", []),
            "description": data.get("description", ""),
            "intents": data.get("intents", []),
            "resources": [r if isinstance(r, dict) else r.dict() for r in data["resources"]],
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
        }
        
        try:
            self.table.put_item(Item=item)
            logger.info(f"Created pathway resource {resource_id} by {data['clinician_id']}")
            return self._to_response(item)
        except ClientError as e:
            logger.error(f"Error creating pathway resource: {e}")
            raise
    
    # ================================
    # Read
    # ================================
    
    def get_resource(self, resource_id: str) -> Optional[dict]:
        """Get a single resource by ID, excluding soft-deleted."""
        try:
            response = self.table.get_item(Key={"resource_id": resource_id})
            item = response.get("Item")
            if item and not item.get("is_deleted", False):
                return self._to_response(item)
            return None
        except ClientError as e:
            logger.error(f"Error getting resource {resource_id}: {e}")
            raise
    
    def list_resources(self, clinician_id: Optional[str] = None) -> List[dict]:
        """
        List all non-deleted resources.
        
        If clinician_id is provided, filters to that clinician's resources
        using the GSI. Otherwise scans the full table.
        """
        try:
            if clinician_id:
                response = self.table.query(
                    IndexName="clinician_id-index",
                    KeyConditionExpression=boto3.dynamodb.conditions.Key("clinician_id").eq(clinician_id),
                )
            else:
                response = self.table.scan()
            
            items = response.get("Items", [])
            return [
                self._to_response(item)
                for item in items
                if not item.get("is_deleted", False)
            ]
        except ClientError as e:
            logger.error(f"Error listing pathway resources: {e}")
            raise
    
    # ================================
    # Update
    # ================================
    
    def update_resource(self, resource_id: str, data: dict) -> Optional[dict]:
        """
        Update an existing resource (full or partial).
        
        Returns the updated resource dict, or None if not found.
        """
        existing = self._get_raw(resource_id)
        if not existing or existing.get("is_deleted", False):
            return None
        
        now = datetime.utcnow().isoformat() + "Z"
        
        if "clinician_name" in data and data["clinician_name"] is not None:
            existing["clinician_name"] = data["clinician_name"]
        if "clinician_id" in data and data["clinician_id"] is not None:
            existing["clinician_id"] = data["clinician_id"]
        if "pathway_stage_ids" in data and data["pathway_stage_ids"] is not None:
            existing["pathway_stage_ids"] = data["pathway_stage_ids"]
        if "description" in data and data["description"] is not None:
            existing["description"] = data["description"]
        if "intents" in data and data["intents"] is not None:
            existing["intents"] = data["intents"]
        if "resources" in data and data["resources"] is not None:
            existing["resources"] = [
                r if isinstance(r, dict) else r.dict() for r in data["resources"]
            ]
        
        existing["updated_at"] = now
        
        try:
            self.table.put_item(Item=existing)
            logger.info(f"Updated pathway resource {resource_id}")
            return self._to_response(existing)
        except ClientError as e:
            logger.error(f"Error updating resource {resource_id}: {e}")
            raise
    
    # ================================
    # Delete (soft)
    # ================================
    
    def delete_resource(self, resource_id: str) -> bool:
        """
        Soft-delete a resource.
        
        Returns True if deleted, False if not found.
        """
        existing = self._get_raw(resource_id)
        if not existing or existing.get("is_deleted", False):
            return False
        
        now = datetime.utcnow().isoformat() + "Z"
        
        try:
            self.table.update_item(
                Key={"resource_id": resource_id},
                UpdateExpression="SET is_deleted = :d, updated_at = :u",
                ExpressionAttributeValues={":d": True, ":u": now},
            )
            logger.info(f"Soft-deleted pathway resource {resource_id}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting resource {resource_id}: {e}")
            raise
    
    # ================================
    # Patient-Facing Query
    # ================================
    
    def get_resources_for_stage(self, stage_id: str) -> List[dict]:
        """
        Get all resources relevant to a patient's pathway stage.
        
        Uses hierarchical matching: a resource tagged with stage "2"
        will also appear for patients on stage "2.1" or "2.1.1".
        """
        ancestor_ids = self._get_ancestor_chain(stage_id)
        
        try:
            response = self.table.scan()
            items = response.get("Items", [])
            
            results = []
            for item in items:
                if item.get("is_deleted", False):
                    continue
                
                tagged_stages = set(item.get("pathway_stage_ids", []))
                if tagged_stages.intersection(ancestor_ids):
                    for res in item.get("resources", []):
                        results.append({
                            "title": res.get("title", ""),
                            "description": item.get("description", ""),
                            "url": res.get("url", ""),
                            "type": res.get("type", "link"),
                            "intents": item.get("intents", []),
                        })
            
            return results
        except ClientError as e:
            logger.error(f"Error querying resources for stage {stage_id}: {e}")
            raise
    
    # ================================
    # Helpers
    # ================================
    
    def _get_raw(self, resource_id: str) -> Optional[dict]:
        """Get raw DynamoDB item (including soft-deleted)."""
        try:
            response = self.table.get_item(Key={"resource_id": resource_id})
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error getting raw resource {resource_id}: {e}")
            raise
    
    @staticmethod
    def _get_ancestor_chain(stage_id: str) -> set:
        """
        Build the set of a stage ID and all its ancestors.
        
        "2.1.1" -> {"2.1.1", "2.1", "2"}
        """
        ids = {stage_id}
        current = stage_id
        while "." in current:
            current = current.rsplit(".", 1)[0]
            ids.add(current)
        return ids
    
    @staticmethod
    def _to_response(item: dict) -> dict:
        """Convert a DynamoDB item to the API response shape."""
        resources_list = item.get("resources", [])
        cleaned = []
        for r in resources_list:
            cleaned.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "type": r.get("type", "link"),
            })
        
        return {
            "id": item["resource_id"],
            "clinician_name": item.get("clinician_name", ""),
            "clinician_id": item.get("clinician_id", ""),
            "pathway_stage_ids": item.get("pathway_stage_ids", []),
            "description": item.get("description", ""),
            "intents": item.get("intents", []),
            "resources": cleaned,
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
        }


# ================================
# Singleton
# ================================

_service_instance: Optional[PathwayResourceService] = None


def get_pathway_resource_service() -> PathwayResourceService:
    global _service_instance
    if _service_instance is None:
        _service_instance = PathwayResourceService()
    return _service_instance
