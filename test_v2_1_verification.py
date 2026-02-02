#!/usr/bin/env python3
"""
Quick test to see if V2.1 is working on the running server.
This will make a test API call and check the logs.
"""

import requests
import json

print("Testing V2.1 Verification Question Integration")
print("=" * 60)

# Test with lumpectomy prompt
test_payload = {
    "message": "I just had a lumpectomy yesterday. The surgeon removed the tumor but kept my breast.",
    "user_id": "test_user_123",  # You can use your actual user ID
    "conversation_id": "test_conv"
}

print("\n📤 Sending test message...")
print(f"Message: {test_payload['message'][:60]}...")

try:
    response = requests.post(
        "http://localhost:8000/api/v2/chat",
        json=test_payload,
        timeout=30
    )
    
    print(f"\n📥 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        response_text = data.get('response', '')
        
        print(f"\nResponse Preview:")
        print("-" * 60)
        print(response_text[:200])
        if len(response_text) > 200:
            print("...")
        print("-" * 60)
        
        # Check if verification question is present
        has_vq_pattern = "Is your surgery to remove" in response_text
        has_confirmation = "It sounds like you might be in the" in response_text
        
        print("\n✅ RESULTS:")
        print(f"  Stage confirmation pattern: {'✅ YES' if has_confirmation else '❌ NO'}")
        print(f"  Verification question: {'✅ YES' if has_vq_pattern else '❌ NO'}")
        
        if has_vq_pattern:
            print("\n🎉 V2.1 VERIFICATION QUESTIONS ARE WORKING!")
        elif has_confirmation:
            print("\n⚠️ Stage confirmation triggered but VQ not injected")
            print("   This means V2.1 wrapper may not be installed")
        else:
            print("\n⚠️ No stage confirmation triggered")
            print("   User may already be in correct stage or certainty too low")
        
        print(f"\nStage inferred: {data.get('stage', 'unknown')}")
        print(f"Intent: {data.get('intent', 'unknown')}")
        
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text[:500])

except Exception as e:
    print(f"\n❌ Test failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Check the backend server logs for [V2.1] messages")
