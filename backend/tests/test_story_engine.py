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


@pytest.fixture
def real_engine():
    """Engine loaded with the shipped beats.json (incl. endings)."""
    return StoryEngine(data_dir="data")


class TestLearningTriggers:
    def test_min_vocab_gates_bonus_beat(self, real_engine):
        base = dict(day=10, score=50.0, flags={}, completed_beats=[
            "saitama_mentioned", "mother_called", "family_story_told",
            "family_pressure", "doubt_shared", "kawagoe_planned",
            "kawagoe_visited", "resolution_idea", "arc1_resolved", "new_chapter",
        ])
        # Main arc done, not enough vocab -> no beat
        beat = real_engine.select_beat(**base, vocab_count=10)
        assert beat is None or beat.id != "bonus_secret_alley"
        # Enough vocab -> bonus fires
        beat = real_engine.select_beat(**base, vocab_count=60)
        assert beat is not None and beat.id == "bonus_secret_alley"

    def test_min_level_gates_phone_beat(self, real_engine):
        base = dict(day=10, score=10.0, completed_beats=[
            "saitama_mentioned", "mother_called", "family_story_told",
            "family_pressure",
        ], flags={"saitama_mentioned": True, "mother_called": True,
                  "family_story_told": True, "family_pressure": True})
        beat = real_engine.select_beat(**base, level="N5")
        assert beat is None or beat.id != "bonus_mother_phone"
        beat = real_engine.select_beat(**base, level="N4")
        assert beat is not None and beat.id == "bonus_mother_phone"

    def test_main_arc_takes_precedence_over_bonus(self, real_engine):
        # Day 5, high vocab, but saitama_mentioned still pending ->
        # the main beat wins (file order)
        beat = real_engine.select_beat(
            day=5, score=50.0, flags={}, completed_beats=[], vocab_count=100,
        )
        assert beat.id == "saitama_mentioned"


class TestEndingSelection:
    ALL_MAIN = [
        "saitama_mentioned", "mother_called", "family_story_told",
        "family_pressure", "doubt_shared", "kawagoe_planned",
        "kawagoe_visited", "resolution_idea", "arc1_resolved", "new_chapter",
        "departure_shadow", "last_evening",
        "bonus_secret_alley", "bonus_mother_phone",
    ]

    def _flags(self, **extra):
        flags = {b: True for b in self.ALL_MAIN}
        flags.update(extra)
        return flags

    def test_no_ending_before_day_90(self, real_engine):
        beat = real_engine.select_beat(
            day=89, score=80.0, flags=self._flags(),
            completed_beats=self.ALL_MAIN, topics_mastered=12,
        )
        assert beat is None or beat.type != "ending"

    def test_tourist_is_default(self, real_engine):
        beat = real_engine.select_beat(
            day=90, score=20.0, flags={}, completed_beats=self.ALL_MAIN,
        )
        assert beat.id == "ending_tourist"

    def test_brief_on_bond_only(self, real_engine):
        beat = real_engine.select_beat(
            day=90, score=65.0, flags={}, completed_beats=self.ALL_MAIN,
        )
        assert beat.id == "ending_brief"

    def test_absolvent_on_learning_only(self, real_engine):
        beat = real_engine.select_beat(
            day=90, score=20.0, flags={}, completed_beats=self.ALL_MAIN,
            topics_mastered=9,
        )
        assert beat.id == "ending_absolvent"

    def test_zwei_staedte_on_both(self, real_engine):
        beat = real_engine.select_beat(
            day=90, score=65.0, flags={}, completed_beats=self.ALL_MAIN,
            topics_mastered=9,
        )
        assert beat.id == "ending_zwei_staedte"

    def test_sommerfest_needs_arc_and_everything(self, real_engine):
        beat = real_engine.select_beat(
            day=90, score=80.0, flags=self._flags(arc1_resolved=True),
            completed_beats=self.ALL_MAIN, topics_mastered=12,
        )
        assert beat.id == "ending_sommerfest"

    def test_game_ended_blocks_endings(self, real_engine):
        beat = real_engine.select_beat(
            day=90, score=80.0, flags=self._flags(game_ended=True),
            completed_beats=self.ALL_MAIN + ["ending_sommerfest"],
            topics_mastered=12,
        )
        assert beat is None or beat.type != "ending"

    def test_all_endings_have_epilogue(self, real_engine):
        endings = [b for b in real_engine.beats if b.type == "ending"]
        assert len(endings) == 5
        assert all(b.epilogue for b in endings)
        assert all(b.sets_flag == "game_ended" for b in endings)
