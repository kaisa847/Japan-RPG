"""Tests for the story beat engine."""

import json

import pytest

from backend.story_engine import StoryEngine


@pytest.fixture
def engine(tmp_path):
    beats = {
        "arc": "test",
        "beats": [
            {
                "id": "beat_one",
                "title": "Erster Beat",
                "trigger": {"min_day": 1, "min_score": 0, "required_flags": []},
                "sets_flag": "flag_one",
                "direction": "Erwähne X.",
            },
            {
                "id": "beat_two",
                "title": "Zweiter Beat",
                "trigger": {"min_day": 3, "min_score": 30, "required_flags": ["flag_one"]},
                "sets_flag": "flag_two",
                "direction": "Erzähle {player_name} von Y.",
                "location_hint": "shrine",
                "didactic_hint": "たことがある",
            },
        ],
    }
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    (story_dir / "beats.json").write_text(
        json.dumps(beats, ensure_ascii=False), encoding="utf-8"
    )
    return StoryEngine(data_dir=str(tmp_path))


class TestSelectBeat:
    def test_first_beat_active_at_start(self, engine):
        beat = engine.select_beat(day=1, score=20.0, flags={}, completed_beats=[])
        assert beat is not None
        assert beat.id == "beat_one"

    def test_completed_beats_are_skipped(self, engine):
        beat = engine.select_beat(
            day=1, score=20.0, flags={"flag_one": True},
            completed_beats=["beat_one"],
        )
        # beat_two requires day 3 and score 30 — not eligible yet
        assert beat is None

    def test_second_beat_when_conditions_met(self, engine):
        beat = engine.select_beat(
            day=3, score=35.0, flags={"flag_one": True},
            completed_beats=["beat_one"],
        )
        assert beat is not None
        assert beat.id == "beat_two"

    def test_required_flag_blocks(self, engine):
        beat = engine.select_beat(
            day=5, score=50.0, flags={}, completed_beats=["beat_one"],
        )
        assert beat is None

    def test_min_score_blocks(self, engine):
        beat = engine.select_beat(
            day=5, score=10.0, flags={"flag_one": True},
            completed_beats=["beat_one"],
        )
        assert beat is None

    def test_only_one_beat_at_a_time(self, engine):
        # Even when both would qualify, the first ineligible/incomplete
        # beat in file order wins.
        beat = engine.select_beat(
            day=5, score=50.0, flags={"flag_one": True}, completed_beats=[],
        )
        assert beat.id == "beat_one"


class TestPromptBlock:
    def test_block_contains_direction_and_flag(self, engine):
        beat = engine.get_beat("beat_two")
        block = engine.build_prompt_block(beat, player_name="Kai")
        assert "Erzähle Kai von Y." in block
        assert "<story_flag>flag_two</story_flag>" in block
        assert "shrine" in block
        assert "たことがある" in block

    def test_missing_beats_file(self, tmp_path):
        engine = StoryEngine(data_dir=str(tmp_path))
        assert engine.beats == []
        assert engine.select_beat(1, 0, {}, []) is None
