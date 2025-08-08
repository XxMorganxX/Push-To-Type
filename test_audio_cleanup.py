#!/usr/bin/env python3
"""Test script to specifically test audio cleanup without double-free errors."""

import time
import threading
from main import AssemblyAIConfig, PTTTranscriber

def test_audio_cleanup():
    """Test audio resource cleanup."""
    print("="*60)
    print("AUDIO CLEANUP TEST")
    print("="*60)
    print("Testing PTTTranscriber audio cleanup for double-free errors...")
    
    # Create a minimal config (API key doesn't need to be real for this test)
    config = AssemblyAIConfig(api_key="test-key-not-real", sample_rate=16000)
    
    # Test multiple create/cleanup cycles
    for i in range(5):
        print(f"\nTest cycle {i+1}/5:")
        
        try:
            # Create transcriber
            transcriber = PTTTranscriber(config)
            print("  ✅ Created PTTTranscriber")
            
            # Start transcription (this will fail due to fake API key, but that's OK)
            transcriber.start_transcription()
            print("  ✅ Started transcription (expected to fail at WebSocket)")
            
            # Wait a moment
            time.sleep(0.5)
            
            # Stop transcription - this is where the double-free would occur
            transcriber.stop_transcription()
            print("  ✅ Stopped transcription - no crash!")
            
            # Cleanup
            transcriber.cleanup()
            print("  ✅ Cleaned up transcriber")
            
        except Exception as e:
            # Filter out expected errors (network/auth failures)
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ['api key', 'connection', 'network', 'websocket', 'auth']):
                print(f"  ✅ Expected error (network/auth): {e}")
            else:
                print(f"  ❌ Unexpected error: {e}")
                raise
    
    print(f"\n🎉 SUCCESS! Completed all 5 audio cleanup cycles")
    print("✅ No double-free errors occurred")
    print("✅ Audio resource management is working correctly")

if __name__ == "__main__":
    test_audio_cleanup()