"""Tests for episodic memory, vocab notebook, promises and story state."""

import pytest

from backend.state_manager import (
    MAX_MEMORIES,
    MAX_OPEN_PROMISES,
    StateManager,
)


@pytest.fixture
def sm(tmp_path):
    return StateManager(data_dir=str(tmp_path))


class TestEpisodicMemory:
    def test_add_memory(self, sm):
        sm.add_memory("Erstes Treffen am Bahnhof.")
        assert len(sm.state.memories) == 1
        assert sm.state.memories[0].text == "Erstes Treffen am Bahnhof."
        assert sm.state.memories[0].day == sm.state.time.day

    def test_empty_memory_ignored(self, sm):
        sm.add_memory("")
        sm.add_memory("   ")
        assert sm.state.memories == []

    def test_memory_truncated(self, sm):
        sm.add_memory("x" * 1000)
        assert len(sm.state.memories[0].text) <= 240

    def test_memory_cap(self, sm):
        for i in range(MAX_MEMORIES + 5):
            sm.add_memory(f"Erinnerung {i}")
        assert len(sm.state.memories) == MAX_MEMORIES
        # Oldest entries dropped
        assert sm.state.memories[0].text == "Erinnerung 5"

    def test_memory_survives_save_load(self, sm, tmp_path):
        sm.add_memory("Persistente Erinnerung")
        sm.save()
        sm2 = StateManager(data_dir=str(tmp_path))
        assert sm2.state.memories[0].text == "Persistente Erinnerung"


class TestVocabNotebook:
    def test_new_vocab_added(self, sm):
        sm.process_vocab([
            {"word": "駅", "reading": "えき", "meaning_de": "Bahnhof"},
        ])
        assert "駅" in sm.state.learning.vocab
        v = sm.state.learning.vocab["駅"]
        assert v.reading == "えき"
        assert v.meaning_de == "Bahnhof"
        assert v.times_seen == 1

    def test_reencounter_strengthens(self, sm):
        sm.process_vocab([{"word": "駅", "reading": "えき", "meaning_de": "Bahnhof"}])
        before = sm.state.learning.vocab["駅"].strength
        sm.process_vocab([{"word": "駅"}])
        after = sm.state.learning.vocab["駅"].strength
        assert after > before
        assert sm.state.learning.vocab["駅"].times_seen == 2

    def test_empty_word_ignored(self, sm):
        sm.process_vocab([{"word": "", "meaning_de": "leer"}])
        assert sm.state.learning.vocab == {}

    def test_due_vocab_requires_day_gap(self, sm):
        sm.process_vocab([{"word": "駅", "reading": "えき", "meaning_de": "Bahnhof"}])
        # Same day → not yet due
        assert sm.get_due_vocab() == []
        sm.state.time.day = 2
        due = sm.get_due_vocab()
        assert len(due) == 1
        assert due[0].word == "駅"

    def test_due_vocab_sorted_weakest_first(self, sm):
        sm.process_vocab([
            {"word": "駅", "meaning_de": "Bahnhof"},
            {"word": "喉", "meaning_de": "Hals"},
        ])
        # Strengthen 駅
        sm.process_vocab([{"word": "駅"}])
        sm.state.time.day = 3
        due = sm.get_due_vocab()
        assert due[0].word == "喉"

    def test_strong_vocab_not_due(self, sm):
        sm.process_vocab([{"word": "駅", "meaning_de": "Bahnhof"}])
        for _ in range(10):
            sm.process_vocab([{"word": "駅"}])
        sm.state.time.day = 5
        assert sm.get_due_vocab() == []


class TestPromises:
    def test_add_and_resolve(self, sm):
        sm.add_promise("Morgen um 10 am Schrein treffen")
        assert len(sm.state.open_promises) == 1
        assert sm.resolve_promise("morgen um 10 am schrein treffen")
        assert sm.state.open_promises == []

    def test_fuzzy_resolve(self, sm):
        sm.add_promise("Ausflug nach Kawagoe am Wochenende")
        assert sm.resolve_promise("Kawagoe am Wochenende")
        assert sm.state.open_promises == []

    def test_no_duplicates(self, sm):
        sm.add_promise("Ramen essen gehen")
        sm.add_promise("Ramen essen gehen")
        assert len(sm.state.open_promises) == 1

    def test_promise_cap(self, sm):
        for i in range(MAX_OPEN_PROMISES + 2):
            sm.add_promise(f"Versprechen {i}")
        assert len(sm.state.open_promises) == MAX_OPEN_PROMISES

    def test_promises_in_context_summary(self, sm):
        sm.add_promise("Morgen Karaoke")
        summary = sm.get_context_summary()
        assert "Morgen Karaoke" in summary

    def test_resolve_unknown_returns_false(self, sm):
        assert not sm.resolve_promise("gibt es nicht")


class TestStoryState:
    def test_complete_beat_sets_flag(self, sm):
        sm.complete_story_beat("beat_one", "flag_one")
        assert "beat_one" in sm.state.story.completed_beats
        assert sm.state.flags.get("flag_one") is True

    def test_complete_beat_idempotent(self, sm):
        sm.complete_story_beat("beat_one", "flag_one")
        sm.complete_story_beat("beat_one", "flag_one")
        assert sm.state.story.completed_beats.count("beat_one") == 1


class TestCanonicalTopics:
    def test_analysis_topic_normalized(self, sm):
        sm.process_analysis({
            "grammar_topic": "te-form",
            "mastery_delta": 0.1,
            "affection_deltas": {},
        })
        assert "て-Form" in sm.state.learning.topics
        assert "te-form" not in sm.state.learning.topics

    def test_unknown_topic_dropped(self, sm):
        sm.process_analysis({
            "grammar_topic": "Onomatopoesie im Manga",
            "mastery_delta": 0.1,
            "affection_deltas": {},
        })
        assert sm.state.learning.topics == {}

    def test_jlpt_level_updates(self, sm):
        from backend.grammar_taxonomy import N5_TOPICS
        # Master all N5 topics directly, then trigger one analysis pass
        for t in N5_TOPICS:
            sm.process_analysis({
                "grammar_topic": t,
                "mastery_delta": 1.0,
                "affection_deltas": {},
            })
        assert sm.state.learning.overall_level == "N4"


class TestLearningStatsAndMilestones:
    def test_learning_stats(self, sm):
        sm.process_vocab([{"word": "駅", "meaning_de": "Bahnhof"}])
        sm.process_analysis({"grammar_topic": "て-Form", "mastery_delta": 0.7})
        sm.process_analysis({"grammar_topic": "Partikel は", "mastery_delta": 0.3})
        stats = sm.learning_stats()
        assert stats["vocab_count"] == 1
        assert stats["topics_mastered"] == 1  # only て-Form >= 0.6
        assert stats["level"] == "N5"

    def test_level_milestone_fires_once(self, sm):
        sm.state.learning.overall_level = "N4"
        note = sm.pending_milestone_note("Kai")
        assert note is not None and "N4" in note
        assert sm.pending_milestone_note("Kai") is None

    def test_vocab_milestone_fires_once(self, sm):
        for i in range(55):
            sm.process_vocab([{"word": f"言葉{i}", "meaning_de": "Wort"}])
        note = sm.pending_milestone_note("Kai")
        assert note is not None and "50" in note
        assert sm.pending_milestone_note("Kai") is None

    def test_no_milestone_without_progress(self, sm):
        assert sm.pending_milestone_note("Kai") is None


class TestExp:
    def test_add_exp_returns_event(self, sm):
        ev = sm.add_exp(5, "Grammatik")
        assert ev == {"amount": 5, "reason": "Grammatik"}
        assert sm.state.exp == 5

    def test_exp_floored_at_zero(self, sm):
        sm.add_exp(3, "Test")
        ev = sm.add_exp(-10, "Abzug")
        # Only -3 could actually be applied
        assert ev == {"amount": -3, "reason": "Abzug"}
        assert sm.state.exp == 0

    def test_deduction_at_zero_is_noop(self, sm):
        assert sm.add_exp(-2, "Abzug") is None
        assert sm.state.exp == 0

    def test_zero_amount_is_noop(self, sm):
        assert sm.add_exp(0, "Nichts") is None

    def test_exp_survives_save_load(self, sm, tmp_path):
        sm.add_exp(42, "Test")
        sm.save()
        sm2 = StateManager(data_dir=str(tmp_path))
        assert sm2.state.exp == 42

    def test_process_vocab_counts_new_words_only(self, sm):
        n = sm.process_vocab([
            {"word": "駅", "meaning_de": "Bahnhof"},
            {"word": "喉", "meaning_de": "Hals"},
        ])
        assert n == 2
        # Re-encounter + one genuinely new word
        n = sm.process_vocab([{"word": "駅"}, {"word": "国", "meaning_de": "Land"}])
        assert n == 1

    def test_prologue_save_slot_name(self, sm):
        sm.state.phase = "prologue"
        meta = sm.save_to_slot(1)
        assert meta.name == "Prolog — Forum-Chat"

    def test_main_save_slot_name_unchanged(self, sm):
        meta = sm.save_to_slot(2)
        assert meta.name.startswith("Tag 1")
