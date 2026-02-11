"""
Patient Profile Service
DynamoDB CRUD operations for patient profiles.

Manages persistent patient profiles for authenticated users.
Uses only user-provided data (no inference).
"""

import logging
from datetime import datetime, date
from typing import Optional, Dict
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from config.settings import settings
from config.pipeline_config import PatientStage
from models.patient_profile import (
    PatientProfile,
    PatientExplicitData,
    PatientStageHistory,
    OnboardingRequest,
    SITUATION_TO_STAGE,
    STAGE_ID_TO_PATIENT_STAGE,
)

logger = logging.getLogger(__name__)


class PatientProfileService:
    """
    Manages patient profiles in DynamoDB.
    
    Provides CRUD operations for:
    - Profile creation and retrieval
    - Onboarding data saving
    - Stage updates with history tracking
    """
    
    def __init__(self):
        self.table_name = "PatientProfiles"
        self.dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
        self.table = self.dynamodb.Table(self.table_name)
    
    async def get_profile(self, user_id: str) -> Optional[PatientProfile]:
        """
        Get profile by Firebase UID.
        
        Args:
            user_id: Firebase UID from JWT token
            
        Returns:
            PatientProfile if found, None otherwise
        """
        try:
            response = self.table.get_item(Key={'user_id': user_id})
            item = response.get('Item')
            
            if item:
                # Parse the item back to PatientProfile
                profile = self._parse_dynamodb_item(item)
                logger.info(f"Retrieved profile for user {user_id}: stage={profile.current_stage}")
                return profile
            
            logger.info(f"No profile found for user {user_id}")
            return None
            
        except ClientError as e:
            logger.error(f"Error getting profile for {user_id}: {e}")
            raise
    
    async def create_profile(self, user_id: str) -> PatientProfile:
        """
        Create a new profile with unknown stage.
        
        Args:
            user_id: Firebase UID from JWT token
            
        Returns:
            Newly created PatientProfile
        """
        now = datetime.utcnow()
        
        profile = PatientProfile(
            user_id=user_id,
            created_at=now,
            updated_at=now,
            current_stage=PatientStage.UNKNOWN,
            onboarding_completed=False,
        )
        
        try:
            self.table.put_item(Item=profile.to_dynamodb_item())
            logger.info(f"Created new profile for user {user_id}")
            return profile
            
        except ClientError as e:
            logger.error(f"Error creating profile for {user_id}: {e}")
            raise
    
    async def get_or_create_profile(self, user_id: str) -> PatientProfile:
        """
        Get existing profile or create a new one.
        
        Args:
            user_id: Firebase UID from JWT token
            
        Returns:
            PatientProfile (existing or newly created)
        """
        profile = await self.get_profile(user_id)
        if profile:
            return profile
        return await self.create_profile(user_id)
    
    async def save_onboarding(
        self, 
        user_id: str, 
        data: OnboardingRequest
    ) -> PatientProfile:
        """
        Save onboarding data and set initial stage.
        
        Args:
            user_id: Firebase UID from JWT token
            data: Onboarding form data
            
        Returns:
            Updated PatientProfile
        """
        # Get or create profile
        profile = await self.get_or_create_profile(user_id)
        
        now = datetime.utcnow()
        
        # Derive broad stage: prefer detailed_stage_id mapping, fall back to situation mapping
        if data.detailed_stage_id and data.detailed_stage_id in STAGE_ID_TO_PATIENT_STAGE:
            new_stage = STAGE_ID_TO_PATIENT_STAGE[data.detailed_stage_id]
        else:
            new_stage = SITUATION_TO_STAGE.get(
                data.current_situation, 
                PatientStage.UNKNOWN
            )
        
        # Parse dates if provided
        diagnosis_date = None
        if data.diagnosis_date:
            try:
                diagnosis_date = date.fromisoformat(data.diagnosis_date)
            except ValueError:
                logger.warning(f"Invalid diagnosis_date format: {data.diagnosis_date}")
        
        treatment_start_date = None
        if data.treatment_start_date:
            try:
                treatment_start_date = date.fromisoformat(data.treatment_start_date)
            except ValueError:
                logger.warning(f"Invalid treatment_start_date format: {data.treatment_start_date}")
        
        # Update profile
        old_stage = profile.current_stage
        profile.current_stage = new_stage
        profile.stage_updated_at = now
        profile.onboarding_completed = True
        profile.onboarding_completed_at = now
        profile.updated_at = now
        
        # Save explicit data
        profile.explicit_data = PatientExplicitData(
            diagnosis_date=diagnosis_date,
            diagnosis_type=data.diagnosis_type,
            current_treatments=data.current_treatments,
            treatment_start_date=treatment_start_date,
        )
        
        # Add to stage history
        profile.stage_history.append(PatientStageHistory(
            timestamp=now,
            from_stage=old_stage if old_stage != PatientStage.UNKNOWN else None,
            to_stage=new_stage,
            source="onboarding",
            to_detailed_stage_id=data.detailed_stage_id,
        ))
        
        # Set detailed stage ID if provided
        if data.detailed_stage_id:
            profile.detailed_stage_id = data.detailed_stage_id
            profile.detailed_stage_updated_at = now
        
        try:
            self.table.put_item(Item=profile.to_dynamodb_item())
            logger.info(
                f"Saved onboarding for user {user_id}: "
                f"stage={new_stage}, situation={data.current_situation}"
            )
            return profile
            
        except ClientError as e:
            logger.error(f"Error saving onboarding for {user_id}: {e}")
            raise
    
    async def update_stage(
        self, 
        user_id: str, 
        new_stage: PatientStage
    ) -> PatientProfile:
        """
        Manually update patient stage with history.
        
        Args:
            user_id: Firebase UID from JWT token
            new_stage: New stage to set
            
        Returns:
            Updated PatientProfile
            
        Raises:
            ValueError: If profile not found
        """
        profile = await self.get_profile(user_id)
        if not profile:
            raise ValueError(f"Profile not found for user {user_id}")
        
        now = datetime.utcnow()
        old_stage = profile.current_stage
        
        # Skip if same stage
        if old_stage == new_stage:
            logger.info(f"Stage unchanged for user {user_id}: {new_stage}")
            return profile
        
        # Update stage
        profile.current_stage = new_stage
        profile.stage_updated_at = now
        profile.updated_at = now
        
        # Clear detailed stage — it belongs to the old broad stage
        # and would be inconsistent if kept
        profile.detailed_stage_id = None
        profile.detailed_stage_label = None
        profile.detailed_stage_updated_at = now
        
        # Add to history
        profile.stage_history.append(PatientStageHistory(
            timestamp=now,
            from_stage=old_stage,
            to_stage=new_stage,
            source="manual_update"
        ))
        
        try:
            self.table.put_item(Item=profile.to_dynamodb_item())
            logger.info(
                f"Updated stage for user {user_id}: "
                f"{old_stage} -> {new_stage}"
            )
            return profile
            
        except ClientError as e:
            logger.error(f"Error updating stage for {user_id}: {e}")
            raise
    
    async def update_stage_detailed(
        self, 
        user_id: str, 
        detailed_stage_id: str,
        detailed_stage_label: str = None
    ) -> PatientProfile:
        """
        Update patient's detailed treatment stage from hierarchical pathway.
        
        Also derives and updates the broad current_stage using
        STAGE_ID_TO_PATIENT_STAGE mapping.
        
        Args:
            user_id: Firebase UID from JWT token
            detailed_stage_id: Stage ID from treatment pathway (e.g., '2.1.1')
            detailed_stage_label: Optional human-readable name (e.g., 'Wide local excision')
            
        Returns:
            Updated PatientProfile
            
        Raises:
            ValueError: If profile not found
        """
        profile = await self.get_profile(user_id)
        if not profile:
            raise ValueError(f"Profile not found for user {user_id}")
        
        now = datetime.utcnow()
        old_stage = profile.current_stage
        
        # Derive the root stage ID (top-level, before the first dot)
        root_id = detailed_stage_id.split('.')[0]
        
        # Update detailed stage
        profile.detailed_stage_id = detailed_stage_id
        profile.detailed_stage_updated_at = now
        profile.updated_at = now
        
        # Store label if provided
        if detailed_stage_label:
            profile.detailed_stage_label = detailed_stage_label
        
        # Also update the broad current_stage using the mapping
        new_stage = STAGE_ID_TO_PATIENT_STAGE.get(root_id)
        if new_stage:
            profile.current_stage = new_stage
            logger.info(
                f"Derived broad stage for {user_id}: "
                f"{root_id} -> {new_stage.value}"
            )
        
        # Record stage history
        history_entry = PatientStageHistory(
            from_stage=old_stage,
            to_stage=profile.current_stage,
            to_detailed_stage_id=detailed_stage_id,
            source="manual_update",
            user_confirmed=True
        )
        if not profile.stage_history:
            profile.stage_history = []
        profile.stage_history.append(history_entry)
        
        try:
            self.table.put_item(Item=profile.to_dynamodb_item())
            logger.info(
                f"Updated detailed stage for user {user_id}: "
                f"{detailed_stage_id} (broad: {profile.current_stage.value})"
            )
            return profile
            
        except ClientError as e:
            logger.error(f"Error updating detailed stage for {user_id}: {e}")
            raise
    
    async def delete_profile(self, user_id: str) -> bool:
        """
        Delete a patient profile.
        
        Args:
            user_id: Firebase UID from JWT token
            
        Returns:
            True if deleted, False if not found
        """
        try:
            self.table.delete_item(Key={'user_id': user_id})
            logger.info(f"Deleted profile for user {user_id}")
            return True
            
        except ClientError as e:
            logger.error(f"Error deleting profile for {user_id}: {e}")
            raise

    async def get_profile_by_ref_id(self, ref_id: str) -> Optional[PatientProfile]:
        """
        Find profile by patient reference ID.
        
        Args:
            ref_id: Patient Reference ID (e.g., 'PAT-XK7M92')
            
        Returns:
            PatientProfile if found, None otherwise
        """
        try:
            # Check for exact match using scan (efficient enough for MVP)
            # For production, use a GSI on patient_ref_id
            response = self.table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('patient_ref_id').eq(ref_id)
            )
            items = response.get('Items', [])
            
            if items:
                return PatientProfile.from_dynamodb_item(items[0])
            return None
            
        except ClientError as e:
            logger.error(f"Error finding profile by ref_id {ref_id}: {e}")
            raise

    async def link_account(self, new_user_id: str, ref_id: str) -> PatientProfile:
        """
        Link a profile from another account to the current user.
        
        This moves the profile ownership:
        1. Find source profile by ref_id
        2. Create copy with new_user_id
        3. Delete old profile
        
        Args:
            new_user_id: Current authenticated user ID
            ref_id: Patient Reference ID to link
            
        Returns:
            The linked (copied) PatientProfile
            
        Raises:
            ValueError: If profile not found or already linked
        """
        # 1. Find source profile
        source_profile = await self.get_profile_by_ref_id(ref_id)
        if not source_profile:
            raise ValueError(f"No profile found with Reference ID: {ref_id}")
            
        if source_profile.user_id == new_user_id:
            raise ValueError("This profile is already linked to your account")
            
        logger.info(f"Linking profile {ref_id} from {source_profile.user_id} to {new_user_id}")
        
        # 2. Create copy for new user
        new_profile = source_profile.copy(deep=True)
        new_profile.user_id = new_user_id
        new_profile.updated_at = datetime.utcnow()
        
        # Save new profile
        try:
            self.table.put_item(Item=new_profile.to_dynamodb_item())
            
            # 3. Delete old profile (transfer ownership)
            await self.delete_profile(source_profile.user_id)
            
            logger.info(f"Successfully linked profile {ref_id} to {new_user_id}")
            return new_profile
            
        except ClientError as e:
            logger.error(f"Error linking profile for {new_user_id}: {e}")
            raise
    
    def _parse_dynamodb_item(self, item: dict) -> PatientProfile:
        """
        Parse DynamoDB item back to PatientProfile.
        
        Handles type conversions (Decimal to float, strings to dates, etc.)
        """
        # Convert Decimal to appropriate types
        def convert_decimals(obj):
            if isinstance(obj, dict):
                return {k: convert_decimals(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_decimals(i) for i in obj]
            elif isinstance(obj, Decimal):
                return float(obj)
            return obj
        
        item = convert_decimals(item)
        
        # Parse datetime strings
        for key in ['created_at', 'updated_at', 'stage_updated_at', 'onboarding_completed_at']:
            if item.get(key) and isinstance(item[key], str):
                try:
                    item[key] = datetime.fromisoformat(item[key].replace('Z', '+00:00'))
                except ValueError:
                    item[key] = None
        
        # Parse stage_history timestamps
        if item.get('stage_history'):
            for entry in item['stage_history']:
                if entry.get('timestamp') and isinstance(entry['timestamp'], str):
                    try:
                        entry['timestamp'] = datetime.fromisoformat(
                            entry['timestamp'].replace('Z', '+00:00')
                        )
                    except ValueError:
                        entry['timestamp'] = datetime.utcnow()
        
        # Parse explicit_data dates
        if item.get('explicit_data'):
            for key in ['diagnosis_date', 'treatment_start_date', 'treatment_end_date']:
                if item['explicit_data'].get(key) and isinstance(item['explicit_data'][key], str):
                    try:
                        item['explicit_data'][key] = date.fromisoformat(item['explicit_data'][key])
                    except ValueError:
                        item['explicit_data'][key] = None
        
        return PatientProfile(**item)

    # ===== Merged from profile_service_v2_1.py =====

    async def update_stage_with_metadata(
        self,
        user_id: str,
        new_stage: PatientStage,
        new_detailed_stage_id: Optional[str] = None,
        new_detailed_stage_label: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> 'PatientProfile':
        """
        Enhanced stage update with transition metadata.

        Args:
            user_id: Firebase UID
            new_stage: New patient stage
            new_detailed_stage_id: Detailed stage ID (e.g., '2.1.1')
            metadata: {
                'source': 'llm_inference' | 'verification' | 'manual_update',
                'certainty': 'HIGH' | 'MEDIUM' | 'LOW',
                'signals': List[str],
                'was_regression': bool,
                'regression_type': 'recurrence' | 'new_primary' | None,
                'user_confirmed': bool,
                'treatment_type': str,
                'transition_notes': str
            }

        Returns:
            Updated PatientProfile with enhanced history
        """
        profile = await self.get_profile(user_id)
        if not profile:
            raise ValueError(f"Profile not found for user {user_id}")

        now = datetime.utcnow()
        old_stage = profile.current_stage
        old_detailed_id = profile.detailed_stage_id

        metadata = metadata or {}

        # Skip if same stage (unless metadata indicates regression)
        if old_stage == new_stage and not metadata.get('was_regression'):
            logger.info(f"Stage unchanged for user {user_id}: {new_stage}")
            return profile

        # Update profile
        profile.current_stage = new_stage
        profile.stage_updated_at = now
        profile.updated_at = now

        # Reset sub-stage tracking for new broad stage
        profile.sub_stage_asked = False

        if new_detailed_stage_id:
            profile.detailed_stage_id = new_detailed_stage_id
            profile.detailed_stage_label = new_detailed_stage_label
            profile.detailed_stage_updated_at = now
        else:
            # Clear stale detailed stage when broad stage changes
            # without a new detailed ID
            profile.detailed_stage_id = None
            profile.detailed_stage_label = None
            profile.detailed_stage_updated_at = now

        # Update stage certainty
        if metadata.get('certainty'):
            profile.current_stage_certainty = metadata['certainty']
            profile.detailed_stage_certainty = metadata['certainty']

        # Track regression if detected
        if metadata.get('was_regression'):
            profile.is_regression_detected = True
            if metadata.get('regression_type') == 'recurrence':
                profile.has_recurrence = True
                profile.recurrence_date = now

        # Track verification
        if metadata.get('user_confirmed'):
            profile.last_verification_at = now

        # Create enhanced history entry
        history_entry = PatientStageHistory(
            timestamp=now,
            from_stage=old_stage,
            to_stage=new_stage,
            source=metadata.get('source', 'manual_update'),
            inference_certainty=metadata.get('certainty'),
            inference_signals=metadata.get('signals', []),
            user_confirmed=metadata.get('user_confirmed', False),
            from_detailed_stage_id=old_detailed_id,
            to_detailed_stage_id=new_detailed_stage_id,
            treatment_type=metadata.get('treatment_type'),
            transition_notes=metadata.get('transition_notes'),
            was_regression=metadata.get('was_regression', False)
        )

        profile.stage_history.append(history_entry)

        try:
            self.table.put_item(Item=profile.to_dynamodb_item())
            logger.info(
                f"Updated stage for user {user_id}: {old_stage} -> {new_stage} "
                f"(detailed: {old_detailed_id} -> {new_detailed_stage_id}, "
                f"source: {metadata.get('source')}, regression: {metadata.get('was_regression')})"
            )
            return profile
        except Exception as e:
            logger.error(f"Error updating stage with metadata for {user_id}: {e}")
            raise

# ================================
# Singleton Instance
# ================================

_service_instance: Optional[PatientProfileService] = None


def get_patient_profile_service() -> PatientProfileService:
    """Get or create the PatientProfileService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = PatientProfileService()
    return _service_instance
