"""Text-to-Speech service using Style-BERT-VITS2 for emotional Japanese speech.

Uses the JVNV F1 (female Japanese) pretrained model with 7 emotion styles:
Neutral, Angry, Disgust, Fear, Happy, Sad, Surprise.

Designed for CPU-only VPS deployment with aggressive resource limits.
"""

import io
import logging
import os
import wave
from pathlib import Path
from typing import Optional

import numpy as np

# Limit CPU usage BEFORE importing torch - critical for VPS stability.
# OMP and MKL threads control low-level parallelism in numpy/torch.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

logger = logging.getLogger(__name__)

# Mapping from Aoi's 16 sprite expressions to JVNV voice styles.
# Each entry is (style_name, style_weight, sdp_ratio, length_scale).
#   - style_name: one of the 7 JVNV styles
#   - style_weight: how strongly the emotion is applied (0.0 - ~2.0)
#   - sdp_ratio: speech tempo variation (0 = monotone, 1 = dynamic)
#   - length_scale: speech speed (< 1.0 = faster, > 1.0 = slower)
EXPRESSION_VOICE_MAP: dict[str, tuple[str, float, float, float]] = {
    "neutral":      ("Neutral",  0.5, 0.2, 1.0),
    "happy":        ("Happy",    1.0, 0.4, 0.95),
    "excited":      ("Happy",    1.5, 0.5, 0.9),
    "curious":      ("Neutral",  0.5, 0.3, 1.0),
    "talking":      ("Neutral",  0.3, 0.3, 0.95),
    "laughing":     ("Happy",    1.5, 0.5, 0.9),
    "surprised":    ("Surprise", 1.2, 0.5, 0.95),
    "thinking":     ("Neutral",  0.3, 0.2, 1.05),
    "embarrassed":  ("Happy",    0.4, 0.3, 1.0),
    "determined":   ("Angry",    0.6, 0.4, 0.95),
    "worried":      ("Sad",      0.8, 0.3, 1.05),
    "sleepy":       ("Neutral",  0.2, 0.1, 1.1),
    "angry":        ("Angry",    1.2, 0.5, 0.95),
    "disgusted":    ("Disgust",  1.0, 0.4, 1.0),
    "shocked":      ("Surprise", 1.5, 0.6, 0.9),
    "ahegao":       ("Happy",    1.5, 0.5, 0.9),
}

DEFAULT_VOICE_PARAMS = ("Neutral", 0.5, 0.2, 1.0)

# CPU performance limits
MAX_TORCH_THREADS = 2
MAX_TTS_TEXT_LENGTH = 100  # Characters - keep short for CPU inference

# HuggingFace model identifiers
HF_REPO_BERT = "ku-nlp/deberta-v2-large-japanese-char-wwm"
HF_REPO_JVNV = "litagin/style_bert_vits2_jvnv"
JVNV_MODEL_NAME = "jvnv-F1-jp"
JVNV_MODEL_FILES = [
    f"{JVNV_MODEL_NAME}/config.json",
    f"{JVNV_MODEL_NAME}/jvnv-F1-jp_e160_s14000.safetensors",
    f"{JVNV_MODEL_NAME}/style_vectors.npy",
]


class TTSService:
    """Manages Style-BERT-VITS2 model loading and inference."""

    def __init__(self, model_dir: str | Path = "data/tts_models"):
        self.model_dir = Path(model_dir)
        self._model = None
        self._ready = False
        self._loading = False
        self._error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def status(self) -> dict:
        if self._ready:
            return {"status": "ready"}
        if self._loading:
            return {"status": "loading"}
        if self._error:
            return {"status": "error", "detail": self._error}
        return {"status": "not_initialized"}

    def models_downloaded(self) -> bool:
        """Check whether all required model files exist locally."""
        for f in JVNV_MODEL_FILES:
            if not (self.model_dir / f).exists():
                return False
        return True

    def download_models(self) -> None:
        """Download JVNV model files from HuggingFace."""
        from huggingface_hub import hf_hub_download

        self.model_dir.mkdir(parents=True, exist_ok=True)
        for f in JVNV_MODEL_FILES:
            target = self.model_dir / f
            if not target.exists():
                logger.info("Downloading TTS model file: %s", f)
                hf_hub_download(
                    HF_REPO_JVNV, f, local_dir=str(self.model_dir),
                )
        logger.info("All TTS model files downloaded to %s", self.model_dir)

    def load(self) -> None:
        """Load BERT models and TTS model into memory.

        This is slow on first run (downloads ~1.5 GB of BERT weights).
        Subsequent runs use the HuggingFace cache.
        """
        if self._ready or self._loading:
            return
        self._loading = True
        self._error = None

        try:
            # Import here to avoid import errors when TTS deps aren't installed
            from style_bert_vits2.constants import Languages
            from style_bert_vits2.nlp import bert_models
            from style_bert_vits2.tts_model import TTSModel

            # 1. Limit PyTorch CPU threads to avoid saturating the VPS
            import torch
            torch.set_num_threads(MAX_TORCH_THREADS)
            torch.set_num_interop_threads(MAX_TORCH_THREADS)
            logger.info(
                "PyTorch threads limited to %d (inter-op: %d)",
                torch.get_num_threads(), torch.get_num_interop_threads(),
            )

            # 2. Load BERT tokenizer and model (cached by HuggingFace)
            logger.info("Loading BERT tokenizer for Japanese TTS...")
            bert_models.load_tokenizer(Languages.JP, HF_REPO_BERT)
            logger.info("Loading BERT model for Japanese TTS...")
            bert_model = bert_models.load_model(Languages.JP, HF_REPO_BERT)
            if isinstance(bert_model, torch.nn.Module):
                bert_model.float()
                bert_model.eval()
                logger.info("Converted BERT model to float32 + eval mode.")

            # 3. Ensure TTS model files are present
            if not self.models_downloaded():
                logger.info("TTS model files not found, downloading...")
                self.download_models()

            # 4. Load the TTS model
            model_file = self.model_dir / JVNV_MODEL_FILES[1]  # safetensors
            config_file = self.model_dir / JVNV_MODEL_FILES[0]  # config.json
            style_file = self.model_dir / JVNV_MODEL_FILES[2]   # style_vectors.npy

            logger.info("Loading TTS model: %s", JVNV_MODEL_NAME)
            self._model = TTSModel(
                model_path=model_file,
                config_path=config_file,
                style_vec_path=style_file,
                device="cpu",
            )

            # Force all weights to float32 for CPU inference.
            # The safetensors file may contain float16 weights which cause
            # dtype mismatches on CPU (c10::Half vs float).
            net_g = getattr(self._model, "net_g", None)
            if net_g is not None and isinstance(net_g, torch.nn.Module):
                net_g.float()
                logger.info("Converted TTS model weights to float32.")

            self._ready = True
            logger.info("TTS service ready (CPU mode).")

        except Exception as e:
            self._error = str(e)
            logger.error("Failed to initialize TTS service: %s", e)
            raise
        finally:
            self._loading = False

    def synthesize(
        self,
        text: str,
        expression: str = "neutral",
    ) -> bytes:
        """Generate speech audio for the given Japanese text and expression.

        Args:
            text: Japanese text to speak (truncated to MAX_TTS_TEXT_LENGTH).
            expression: One of Aoi's 16 expression names.

        Returns:
            WAV audio data as bytes.
        """
        if not self._ready or self._model is None:
            raise RuntimeError("TTS service is not initialized. Call load() first.")

        # Truncate long text to keep inference fast on CPU.
        # Try to cut at a sentence boundary (。！？) for natural output.
        if len(text) > MAX_TTS_TEXT_LENGTH:
            truncated = text[:MAX_TTS_TEXT_LENGTH]
            for sep in ("。", "！", "？", "!", "?", "、", ","):
                idx = truncated.rfind(sep)
                if idx > 0:
                    truncated = truncated[: idx + 1]
                    break
            text = truncated
            logger.debug("TTS text truncated to %d chars", len(text))

        style, style_weight, sdp_ratio, length_scale = EXPRESSION_VOICE_MAP.get(
            expression, DEFAULT_VOICE_PARAMS,
        )

        import torch
        from style_bert_vits2.constants import Languages

        with torch.inference_mode():
            sr, audio = self._model.infer(
                text=text,
                language=Languages.JP,
                style=style,
                style_weight=style_weight,
                sdp_ratio=sdp_ratio,
                length=length_scale,
            )

        return _audio_to_wav(audio, sr)


def _audio_to_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """Convert a numpy float audio array to WAV bytes."""
    # Normalize to int16 range
    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())

    return buf.getvalue()
