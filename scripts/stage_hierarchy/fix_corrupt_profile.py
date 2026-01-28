"""
Utility script to fix/delete corrupt patient profiles.
"""

import asyncio
import os
import sys

# Setup path for imports - adjust for new location
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.patient_profile_service import PatientProfileService, get_patient_profile_service

USER_ID = "103030615691229126949"

async def fix_profile():
    print(f"Attempting to delete profile for {USER_ID}...")
    service = get_patient_profile_service()
    try:
        await service.delete_profile(USER_ID)
        print("Profile deleted successfully.")
    except Exception as e:
        print(f"Error deleting profile: {e}")

if __name__ == "__main__":
    asyncio.run(fix_profile())
