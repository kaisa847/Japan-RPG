"""Tests for the TTS service (edge-tts mocked — no network)."""

import sys
import types

import pytest

from backend.tts_service import (
    DEFAULT_VOICE_PARAMS,
    EXPRESSION_VOICE_MAP,
    MAX_TTS_TEXT_LENGTH,
    TTSService,
)

# Records the kwargs of the most recently constructed Communicate instance.
_LAST_CALL: dict = {}


class _FakeCommunicate:
    def __init__(self, text, voice, pitch, rate):
        _LAST_CALL.clear()
        _LAST_CALL.update(text=text, voice=voice, pitch=pitch, rate=rate)

    async def stream(self):
        yield {"type": "audio", "data": b"AUDIO"}
        yield {"type": "WordBoundary"}  # non-audio chunk should be ignored
        yield {"type": "audio", "data": b"DATA"}


@pytest.fixture
def fake_edge_tts(monkeypatch):
    module = types.ModuleType("edge_tts")
    module.Communicate = _FakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", module)
    return module


@pytest.mark.asyncio
class TestTTSService:
    async def test_load_marks_ready(self, fake_edge_tts):
        svc = TTSService()
        await svc.load()
        assert svc.is_ready
        assert svc.status == {"status": "ready"}

    async def test_load_missing_dependency(self, monkeypatch):
        # Simulate edge-tts not being importable.
        monkeypatch.setitem(sys.modules, "edge_tts", None)
        svc = TTSService()
        with pytest.raises(ImportError):
            await svc.load()
        assert svc.status["status"] == "error"

    async def test_synthesize_requires_load(self, fake_edge_tts):
        svc = TTSService()
        with pytest.raises(RuntimeError):
            await svc.synthesize("こんにちは")

    async def test_synthesize_concatenates_audio_chunks(self, fake_edge_tts):
        svc = TTSService()
        await svc.load()
        audio = await svc.synthesize("こんにちは", "happy")
        assert audio == b"AUDIODATA"

    async def test_expression_maps_to_voice_params(self, fake_edge_tts):
        svc = TTSService()
        await svc.load()
        await svc.synthesize("テスト", "excited")
        expected_pitch, expected_rate = EXPRESSION_VOICE_MAP["excited"]
        assert _LAST_CALL["pitch"] == expected_pitch
        assert _LAST_CALL["rate"] == expected_rate

    async def test_unknown_expression_uses_default(self, fake_edge_tts):
        svc = TTSService()
        await svc.load()
        await svc.synthesize("テスト", "no_such_expression")
        assert (_LAST_CALL["pitch"], _LAST_CALL["rate"]) == DEFAULT_VOICE_PARAMS

    async def test_long_text_truncated_at_sentence_boundary(self, fake_edge_tts):
        svc = TTSService()
        await svc.load()
        text = "あ" * 150 + "。" + "い" * 100
        await svc.synthesize(text)
        sent = _LAST_CALL["text"]
        assert len(sent) <= MAX_TTS_TEXT_LENGTH
        assert sent.endswith("。")
