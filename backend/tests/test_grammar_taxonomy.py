"""Tests for the canonical grammar taxonomy and JLPT estimation."""

from backend.grammar_taxonomy import (
    MASTERED_THRESHOLD,
    N4_TOPICS,
    N5_TOPICS,
    estimate_jlpt,
    normalize_topic,
    taxonomy_for_level,
)


class TestNormalizeTopic:
    def test_exact_match(self):
        assert normalize_topic("て-Form") == "て-Form"
        assert normalize_topic("Partikel は") == "Partikel は"

    def test_case_and_whitespace_insensitive(self):
        assert normalize_topic("  て-form  ") == "て-Form"
        assert normalize_topic("partikel  は") == "Partikel は"

    def test_alias_match(self):
        assert normalize_topic("te-form") == "て-Form"
        assert normalize_topic("masu-form") == "です/ます-Form"
        assert normalize_topic("keigo") == "Höflichkeit Keigo Basis"

    def test_substring_match(self):
        # Free-form variants map onto the canonical entry
        assert normalize_topic("て-Form Verlaufsform") == "て-Form Verlaufsform (ている)"

    def test_unknown_topic_dropped(self):
        assert normalize_topic("Onomatopoesie im Manga") is None

    def test_empty(self):
        assert normalize_topic(None) is None
        assert normalize_topic("") is None
        assert normalize_topic("   ") is None


class TestEstimateJlpt:
    @staticmethod
    def _mastered(topics: list[str]) -> dict:
        return {t: {"mastery": MASTERED_THRESHOLD} for t in topics}

    def test_default_n5(self):
        assert estimate_jlpt({}) == "N5"

    def test_few_topics_stay_n5(self):
        topics = self._mastered(N5_TOPICS[:5])
        assert estimate_jlpt(topics) == "N5"

    def test_n5_mastered_gives_n4(self):
        topics = self._mastered(N5_TOPICS)
        assert estimate_jlpt(topics) == "N4"

    def test_n5_and_n4_mastered_gives_n3(self):
        topics = self._mastered(N5_TOPICS + N4_TOPICS)
        assert estimate_jlpt(topics) == "N3"

    def test_low_mastery_does_not_count(self):
        topics = {t: {"mastery": 0.3} for t in N5_TOPICS}
        assert estimate_jlpt(topics) == "N5"

    def test_n4_without_n5_stays_n5(self):
        topics = self._mastered(N4_TOPICS)
        assert estimate_jlpt(topics) == "N5"


class TestTaxonomyForLevel:
    def test_n5_only_sees_n5(self):
        assert taxonomy_for_level("N5") == N5_TOPICS

    def test_n4_sees_both(self):
        assert taxonomy_for_level("N4") == N5_TOPICS + N4_TOPICS

    def test_unknown_level_defaults_to_n5(self):
        assert taxonomy_for_level("banana") == N5_TOPICS
