"""
Dependencies for GDPR consent gating (optional processing paused after data consent withdrawal).
"""

from fastapi import Depends, HTTPException

from api.auth import get_authenticated_user_id
from services.patient_profile_service import get_patient_profile_service


async def require_active_data_processing(user_id: str = Depends(get_authenticated_user_id)) -> str:
    """
    Blocks writes that represent optional health-data processing when the patient has
    withdrawn data-processing consent (data_processing_paused on profile).
    """
    profile = await get_patient_profile_service().get_profile(user_id)
    paused = bool(profile and profile.data_processing_paused)
    if paused:
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    "Data processing consent is withdrawn or paused. "
                    "Re-grant data consent in Settings to continue."
                ),
                "consent_type": "data",
            },
        )
    return user_id
