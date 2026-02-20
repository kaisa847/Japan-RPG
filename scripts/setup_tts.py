#!/usr/bin/env python3
"""Download and verify TTS models for Aoi's voice.

Run this once on the VPS before starting the game server with TTS enabled:

    python scripts/setup_tts.py

This will:
  1. Download the JVNV-F1 (female Japanese) voice model (~200 MB)
  2. Download and cache the BERT tokenizer/model (~1.4 GB, cached by HuggingFace)
  3. Run a test synthesis to verify everything works
"""

import os
import sys
import time
from pathlib import Path

# Limit CPU threads before any torch/numpy imports
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MODEL_DIR = PROJECT_ROOT / "data" / "tts_models"


def main():
    print("=" * 60)
    print("  Aoi TTS Setup - Style-BERT-VITS2 (CPU)")
    print("=" * 60)
    print()

    # Step 1: Check dependencies
    print("[1/4] Checking dependencies...")
    try:
        import style_bert_vits2  # noqa: F401
        import torch  # noqa: F401
        import huggingface_hub  # noqa: F401
        print("  OK - All Python packages found.")
    except ImportError as e:
        print(f"  FEHLER: {e}")
        print()
        print("  Bitte installiere die Abhaengigkeiten:")
        print("    pip install style-bert-vits2 huggingface-hub")
        print("    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu")
        sys.exit(1)

    # Step 2: Download TTS model
    print()
    print("[2/4] Downloading JVNV-F1 voice model...")
    from backend.tts_service import TTSService

    tts = TTSService(model_dir=str(MODEL_DIR))

    if tts.models_downloaded():
        print("  OK - Model files already present.")
    else:
        tts.download_models()
        print("  OK - Model files downloaded.")

    # Step 3: Load models (includes BERT download on first run)
    print()
    print("[3/4] Loading BERT + TTS models (first run downloads ~1.4 GB)...")
    t0 = time.time()
    tts.load()
    elapsed = time.time() - t0
    print(f"  OK - Models loaded in {elapsed:.1f}s.")

    # Step 4: Test synthesis (short text to avoid overloading CPU)
    print()
    print("[4/4] Running test synthesis...")
    t0 = time.time()
    wav_data = tts.synthesize(
        text="こんにちは！",
        expression="happy",
    )
    elapsed = time.time() - t0

    test_path = MODEL_DIR / "test_output.wav"
    test_path.write_bytes(wav_data)
    size_kb = len(wav_data) / 1024

    print(f"  OK - Generated {size_kb:.0f} KB audio in {elapsed:.1f}s.")
    print(f"  Test file: {test_path}")
    print()
    print("=" * 60)
    print("  TTS setup complete! Aoi can now speak.")
    print("=" * 60)


if __name__ == "__main__":
    main()
