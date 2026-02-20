#!/usr/bin/env python3
"""Verify TTS setup for Aoi's voice.

Run this once on the VPS to verify edge-tts works:

    python scripts/setup_tts.py

Uses Microsoft Edge Neural TTS (cloud-based) - no model downloads needed.
"""

import asyncio
import sys
import time
from pathlib import Path

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "data" / "tts_models"


async def main():
    print("=" * 60)
    print("  Aoi TTS Setup - edge-tts (cloud)")
    print("=" * 60)
    print()

    # Step 1: Check dependencies
    print("[1/2] Checking dependencies...")
    try:
        import edge_tts  # noqa: F401
        print("  OK - edge-tts installed.")
    except ImportError:
        print("  FEHLER: edge-tts nicht gefunden.")
        print()
        print("  Bitte installiere:")
        print("    pip install edge-tts")
        sys.exit(1)

    # Step 2: Test synthesis
    print()
    print("[2/2] Running test synthesis...")
    from backend.tts_service import TTSService

    tts = TTSService()
    await tts.load()

    t0 = time.time()
    audio_data = await tts.synthesize(
        text="こんにちは！",
        expression="happy",
    )
    elapsed = time.time() - t0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_path = OUTPUT_DIR / "test_output.mp3"
    test_path.write_bytes(audio_data)
    size_kb = len(audio_data) / 1024

    print(f"  OK - Generated {size_kb:.0f} KB audio in {elapsed:.1f}s.")
    print(f"  Test file: {test_path}")
    print()
    print("=" * 60)
    print("  TTS setup complete! Aoi can now speak.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
