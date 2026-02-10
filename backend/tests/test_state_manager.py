"""Tests for the state manager."""

import json

import pytest

from backend.state_manager import (
    StateManager, GameState, AoiAffection, TimeState,
    TopicMastery, PlayerLearningProfile, MAX_SCENE_HISTORY,
    _period_from_hour,
)


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "data"


class TestStateManager:
    def test_creates_default_state(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        assert sm.state.time.day == 1
        assert sm.state.time.hour == 14
        assert sm.state.time.period == "afternoon"
        assert sm.state.current_location == "shimokitazawa_apartment"
        assert sm.state.current_character == "aoi"

    def test_save_and_reload(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 5
        sm.state.current_character = "aoi"
        sm.save()

        sm2 = StateManager(data_dir=str(tmp_data_dir))
        assert sm2.state.time.day == 5
        assert sm2.state.current_character == "aoi"

    def test_handles_corrupt_json(self, tmp_data_dir):
        tmp_data_dir.mkdir(parents=True, exist_ok=True)
        state_file = tmp_data_dir / "game_state.json"
        state_file.write_text("{ broken json !!!", encoding="utf-8")

        sm = StateManager(data_dir=str(tmp_data_dir))
        assert sm.state.time.day == 1  # default

    def test_reset_returns_fresh_state(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 10
        sm.state.current_character = "aoi"
        sm.add_conversation_turn("user", "test")
        sm.save()

        fresh = sm.reset()
        assert fresh.time.day == 1
        assert fresh.current_character == "aoi"  # default is aoi now
        assert fresh.conversation_history == []

    def test_conversation_history_capping(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        for i in range(30):
            sm.add_conversation_turn("user", f"message {i}")
        assert len(sm.state.conversation_history) == 20
        assert sm.state.conversation_history[0]["content"] == "message 10"

    def test_update_from_scene(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.update_from_scene({
            "background": "cafe_shimokitazawa",
            "character": "aoi",
        })
        assert sm.state.current_background == "cafe_shimokitazawa"
        assert sm.state.current_character == "aoi"

    def test_update_from_scene_no_overwrite_on_none(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.current_background = "apartment_room"
        sm.update_from_scene({"background": None, "character": None})
        assert sm.state.current_background == "apartment_room"

    def test_context_summary_format(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        summary = sm.get_context_summary()
        assert "Tag: 1" in summary
        assert "Uhrzeit:" in summary
        assert "Ort:" in summary
        assert "Aoi-Zuneigung:" in summary

    def test_get_state_dict(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        d = sm.get_state_dict()
        assert isinstance(d, dict)
        assert d["time"]["day"] == 1
        assert "conversation_history" in d

    def test_archive_session(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.add_conversation_turn("user", "hello")
        sm.reset()

        log_path = tmp_data_dir / "session_log.json"
        assert log_path.exists()
        sessions = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(sessions) == 1
        assert sessions[0]["turns"] == 1

    def test_last_scene_default_none(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        assert sm.state.last_scene is None

    def test_last_scene_save_and_restore(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.last_scene = {
            "character": "aoi",
            "expression": "happy",
            "background": "apartment_room",
            "dialog_jp": "テスト",
            "dialog_jp_furigana": "",
            "dialog_de": "Test",
        }
        sm.save()

        sm2 = StateManager(data_dir=str(tmp_data_dir))
        assert sm2.state.last_scene is not None
        assert sm2.state.last_scene["character"] == "aoi"
        assert sm2.state.last_scene["dialog_jp"] == "テスト"

    def test_reset_clears_last_scene(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.last_scene = {"character": "aoi", "dialog_jp": "テスト"}
        sm.save()
        sm.reset()
        assert sm.state.last_scene is None


class TestAoiAffection:
    def test_default_weighted_score(self):
        a = AoiAffection()
        # All at 20: 20*0.35 + 20*0.25 + 20*0.20 + 20*0.10 + 20*0.10 = 20.0
        assert a.weighted_score == pytest.approx(20.0)

    def test_default_tone_is_neutral(self):
        a = AoiAffection()
        assert a.tone == "neutral"

    def test_tone_distant(self):
        a = AoiAffection(
            language_effort=5, cultural_interest=5,
            personal_bond=5, humor=5, reliability=5,
        )
        assert a.tone == "distant"

    def test_tone_friendly(self):
        a = AoiAffection(
            language_effort=50, cultural_interest=50,
            personal_bond=50, humor=50, reliability=50,
        )
        assert a.tone == "friendly"

    def test_tone_warm(self):
        a = AoiAffection(
            language_effort=70, cultural_interest=70,
            personal_bond=70, humor=70, reliability=70,
        )
        assert a.tone == "warm"

    def test_tone_intimate(self):
        a = AoiAffection(
            language_effort=90, cultural_interest=90,
            personal_bond=90, humor=90, reliability=90,
        )
        assert a.tone == "intimate"

    def test_weighted_score_asymmetric(self):
        a = AoiAffection(
            language_effort=100, cultural_interest=0,
            personal_bond=0, humor=0, reliability=0,
        )
        assert a.weighted_score == pytest.approx(35.0)

    def test_to_display_dict(self):
        a = AoiAffection()
        d = a.to_display_dict()
        assert "weighted_score" in d
        assert "tone" in d
        assert d["tone"] == "neutral"


class TestTimeState:
    def test_default_values(self):
        t = TimeState()
        assert t.day == 1
        assert t.hour == 14
        assert t.period == "afternoon"

    def test_advance_hours(self):
        t = TimeState(day=1, hour=14, period="afternoon")
        t.advance_hours(3)
        assert t.hour == 17
        assert t.period == "evening"
        assert t.day == 1

    def test_advance_hours_crosses_midnight(self):
        t = TimeState(day=1, hour=22, period="night")
        t.advance_hours(5)
        assert t.hour == 3
        assert t.day == 2
        assert t.period == "late_night"

    def test_advance_hours_multiple_days(self):
        t = TimeState(day=1, hour=10, period="morning")
        t.advance_hours(50)
        assert t.day == 3
        assert t.hour == 12

    def test_advance_to_next_day(self):
        t = TimeState(day=3, hour=22, period="night")
        t.advance_to_next_day()
        assert t.day == 4
        assert t.hour == 9
        assert t.period == "morning"

    def test_advance_to_next_day_custom_hour(self):
        t = TimeState(day=1, hour=14, period="afternoon")
        t.advance_to_next_day(start_hour=12)
        assert t.day == 2
        assert t.hour == 12
        assert t.period == "midday"

    def test_period_from_hour(self):
        assert _period_from_hour(3) == "late_night"
        assert _period_from_hour(7) == "early_morning"
        assert _period_from_hour(10) == "morning"
        assert _period_from_hour(13) == "midday"
        assert _period_from_hour(15) == "afternoon"
        assert _period_from_hour(18) == "evening"
        assert _period_from_hour(22) == "night"


class TestProcessAnalysis:
    def test_none_analysis_is_noop(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis(None)
        assert sm.state.learning.total_interactions == 0

    def test_updates_total_interactions(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis({"grammar_topic": "greetings", "mastery_delta": 0.1})
        assert sm.state.learning.total_interactions == 1

    def test_creates_new_topic(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis({
            "grammar_topic": "te_form",
            "mastery_delta": 0.15,
        })
        assert "te_form" in sm.state.learning.topics
        tm = sm.state.learning.topics["te_form"]
        assert tm.mastery == pytest.approx(0.15)
        assert tm.attempts == 1
        assert tm.last_seen != ""

    def test_accumulates_mastery(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis({"grammar_topic": "particles", "mastery_delta": 0.3})
        sm.process_analysis({"grammar_topic": "particles", "mastery_delta": 0.2})
        tm = sm.state.learning.topics["particles"]
        assert tm.mastery == pytest.approx(0.5)
        assert tm.attempts == 2

    def test_mastery_clamped_to_1(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis({"grammar_topic": "greetings", "mastery_delta": 1.5})
        assert sm.state.learning.topics["greetings"].mastery == 1.0

    def test_mastery_clamped_to_0(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis({"grammar_topic": "greetings", "mastery_delta": 0.3})
        sm.process_analysis({"grammar_topic": "greetings", "mastery_delta": -0.5})
        assert sm.state.learning.topics["greetings"].mastery == 0.0

    def test_updates_affection(self, tmp_data_dir):
        """Deltas are clamped to ±1 and damped by 0.5, so +5 → +0.5, -2 → -0.5."""
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_analysis({
            "affection_deltas": {
                "language_effort": 5.0,
                "humor": -2.0,
            },
        })
        # +5 clamped to +1, * 0.5 = +0.5 → 20.5
        assert sm.state.affection.language_effort == 20.5
        # -2 clamped to -1, * 0.5 = -0.5 → 19.5
        assert sm.state.affection.humor == 19.5

    def test_affection_clamped_to_100(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.affection.language_effort = 99.8
        sm.process_analysis({
            "affection_deltas": {"language_effort": 10.0},
        })
        # +10 clamped to +1, * 0.5 = +0.5 → 100.0 (capped)
        assert sm.state.affection.language_effort == 100.0

    def test_affection_clamped_to_0(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.affection.humor = 0.3
        sm.process_analysis({
            "affection_deltas": {"humor": -10.0},
        })
        # -10 clamped to -1, * 0.5 = -0.5 → 0.0 (capped)
        assert sm.state.affection.humor == 0.0

    def test_weak_points_calculated(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        # Create topics with varying mastery
        sm.process_analysis({"grammar_topic": "greetings", "mastery_delta": 0.9})
        sm.process_analysis({"grammar_topic": "particles", "mastery_delta": 0.1})
        sm.process_analysis({"grammar_topic": "te_form", "mastery_delta": 0.3})
        sm.process_analysis({"grammar_topic": "counting", "mastery_delta": 0.05})

        weak = sm.state.learning.weak_points
        assert len(weak) == 4
        # counting (0.05) should be first (weakest)
        assert weak[0] == "counting"


class TestProcessTimeUpdate:
    def test_none_is_noop(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_time_update(None)
        assert sm.state.time.hour == 14

    def test_advance_hours(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_time_update("+3h")
        assert sm.state.time.hour == 17
        assert sm.state.time.period == "evening"

    def test_next_day(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_time_update("next_day")
        assert sm.state.time.day == 2
        assert sm.state.time.hour == 9

    def test_invalid_format_ignored(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.process_time_update("invalid")
        assert sm.state.time.hour == 14  # unchanged

    def test_resets_turns_counter_on_advance(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.turns_since_time_advance = 5
        sm.process_time_update("+1h")
        assert sm.state.turns_since_time_advance == 0

    def test_resets_turns_counter_on_next_day(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.turns_since_time_advance = 3
        sm.process_time_update("next_day")
        assert sm.state.turns_since_time_advance == 0

    def test_does_not_reset_counter_on_invalid(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.turns_since_time_advance = 4
        sm.process_time_update("invalid")
        assert sm.state.turns_since_time_advance == 4

    def test_does_not_reset_counter_on_none(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.turns_since_time_advance = 4
        sm.process_time_update(None)
        assert sm.state.turns_since_time_advance == 4


class TestPeriodicTimeAdvance:
    def test_no_advance_before_threshold(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        for _ in range(5):
            sm.maybe_advance_time_periodic()
        assert sm.state.time.hour == 14  # unchanged
        assert sm.state.turns_since_time_advance == 5

    def test_advances_at_threshold(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        for _ in range(6):
            sm.maybe_advance_time_periodic()
        assert sm.state.time.hour == 15  # advanced 1h
        assert sm.state.turns_since_time_advance == 0

    def test_advances_multiple_cycles(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        for _ in range(18):
            sm.maybe_advance_time_periodic()
        # 3 advances of 1h each: 14 → 17
        assert sm.state.time.hour == 17
        assert sm.state.turns_since_time_advance == 0

    def test_explicit_update_resets_periodic_counter(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        # Accumulate 4 turns
        for _ in range(4):
            sm.maybe_advance_time_periodic()
        assert sm.state.turns_since_time_advance == 4
        # Explicit update resets
        sm.process_time_update("+2h")
        assert sm.state.turns_since_time_advance == 0
        assert sm.state.time.hour == 16
        # Next 5 turns should not trigger periodic
        for _ in range(5):
            sm.maybe_advance_time_periodic()
        assert sm.state.time.hour == 16  # still 16


class TestSceneHistory:
    def test_scene_history_default_empty(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        assert sm.state.scene_history == []

    def test_add_scene_to_history(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.add_scene_to_history({
            "character": "aoi",
            "expression": "happy",
            "background": "apartment_room",
            "dialog_jp": "こんにちは",
            "dialog_jp_furigana": "",
            "dialog_de": "Hallo",
        })
        assert len(sm.state.scene_history) == 1
        entry = sm.state.scene_history[0]
        assert entry["character"] == "aoi"
        assert entry["dialog_jp"] == "こんにちは"
        assert entry["dialog_de"] == "Hallo"
        assert "timestamp" in entry

    def test_scene_history_capping(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        for i in range(MAX_SCENE_HISTORY + 20):
            sm.add_scene_to_history({
                "character": "aoi",
                "dialog_jp": f"msg {i}",
                "dialog_de": f"msg {i}",
            })
        assert len(sm.state.scene_history) == MAX_SCENE_HISTORY
        assert sm.state.scene_history[0]["dialog_jp"] == "msg 20"

    def test_scene_history_persisted(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.add_scene_to_history({
            "character": "aoi",
            "dialog_jp": "テスト",
            "dialog_de": "Test",
        })
        sm.save()

        sm2 = StateManager(data_dir=str(tmp_data_dir))
        assert len(sm2.state.scene_history) == 1
        assert sm2.state.scene_history[0]["dialog_jp"] == "テスト"

    def test_reset_clears_scene_history(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.add_scene_to_history({"character": "aoi", "dialog_jp": "テスト"})
        sm.save()
        sm.reset()
        assert sm.state.scene_history == []


class TestSaveSlots:
    def test_save_to_slot_creates_file(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 3
        sm.state.current_character = "aoi"
        meta = sm.save_to_slot(1)
        assert meta.slot_id == 1
        assert meta.day_number == 3
        assert meta.current_character == "aoi"
        assert meta.saved_at != ""
        slot_path = tmp_data_dir / "saves" / "slot_1.json"
        assert slot_path.exists()

    def test_save_to_slot_with_custom_name(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        meta = sm.save_to_slot(2, name="My Save")
        assert meta.name == "My Save"

    def test_save_to_slot_auto_name(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 5
        sm.state.current_background = "cafe_shimokitazawa"
        meta = sm.save_to_slot(1)
        assert "Tag 5" in meta.name
        assert "cafe_shimokitazawa" in meta.name

    def test_save_to_slot_invalid_id(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        with pytest.raises(ValueError):
            sm.save_to_slot(0)
        with pytest.raises(ValueError):
            sm.save_to_slot(10)

    def test_load_from_slot(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 7
        sm.state.current_character = "aoi"
        sm.add_conversation_turn("user", "hello")
        sm.save_to_slot(3)

        sm.state.time.day = 99
        sm.save()

        restored = sm.load_from_slot(3)
        assert restored.time.day == 7
        assert restored.current_character == "aoi"
        assert len(restored.conversation_history) == 1

    def test_load_from_nonexistent_slot(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        with pytest.raises(FileNotFoundError):
            sm.load_from_slot(5)

    def test_list_save_slots_empty(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        slots = sm.list_save_slots()
        assert slots == []

    def test_list_save_slots_with_data(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 2
        sm.save_to_slot(1)
        sm.state.time.day = 5
        sm.save_to_slot(3)

        slots = sm.list_save_slots()
        assert len(slots) == 2
        ids = [s.slot_id for s in slots]
        assert 1 in ids
        assert 3 in ids

    def test_delete_save_slot(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.save_to_slot(2)
        assert sm.delete_save_slot(2) is True
        assert sm.list_save_slots() == []

    def test_delete_nonexistent_slot(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        assert sm.delete_save_slot(5) is False

    def test_overwrite_save_slot(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.time.day = 1
        sm.save_to_slot(1)

        sm.state.time.day = 10
        sm.save_to_slot(1, name="Updated Save")

        slots = sm.list_save_slots()
        assert len(slots) == 1
        assert slots[0].day_number == 10
        assert slots[0].name == "Updated Save"

    def test_save_preserves_scene_history(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.add_scene_to_history({"character": "aoi", "dialog_jp": "テスト"})
        sm.save_to_slot(1)

        sm.state.scene_history = []

        restored = sm.load_from_slot(1)
        assert len(restored.scene_history) == 1
        assert restored.scene_history[0]["dialog_jp"] == "テスト"

    def test_save_preserves_affection(self, tmp_data_dir):
        sm = StateManager(data_dir=str(tmp_data_dir))
        sm.state.affection.language_effort = 75.0
        sm.save_to_slot(1)

        sm.state.affection.language_effort = 20.0
        restored = sm.load_from_slot(1)
        assert restored.affection.language_effort == 75.0
