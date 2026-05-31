"""Tests for the response parser."""

import pytest

from backend.response_parser import (
    ResponseParser,
    _fix_reversed_furigana,
    _has_kanji,
    _is_kanji,
)


class TestParseScene:
    def test_valid_full_scene(self):
        raw = """<scene>
            <character>aoi</character>
            <expression>happy</expression>
            <background>apartment_room</background>
            <dialog_jp>おはよう！元気？</dialog_jp>
            <dialog_jp_furigana>おはよう！元気[げんき]？</dialog_jp_furigana>
            <dialog_de>Guten Morgen! Wie geht's?</dialog_de>
        </scene>"""
        result = ResponseParser.parse_scene(raw)
        assert result.character == "aoi"
        assert result.expression == "happy"
        assert result.background == "apartment_room"
        assert result.dialog_jp == "おはよう！元気？"
        assert result.dialog_jp_furigana == "おはよう！元気[げんき]？"
        assert result.dialog_de == "Guten Morgen! Wie geht's?"
        assert result.parse_errors == []

    def test_scene_with_surrounding_text(self):
        raw = "Here is the scene:\n<scene><character>aoi</character><expression>neutral</expression><background>apartment_room</background><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>\nDone."
        result = ResponseParser.parse_scene(raw)
        assert result.character == "aoi"
        assert result.dialog_jp == "テスト"

    def test_missing_expression_defaults_neutral(self):
        raw = "<scene><character>aoi</character><background>apartment_room</background><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.expression == "neutral"

    def test_invalid_expression_for_aoi(self):
        raw = "<scene><character>aoi</character><expression>deadpan</expression><background>apartment_room</background><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.expression == "neutral"
        assert len(result.parse_errors) > 0
        assert "deadpan" in result.parse_errors[0]

    def test_valid_aoi_expressions(self):
        for expr in [
            "happy",
            "excited",
            "curious",
            "talking",
            "laughing",
            "surprised",
            "thinking",
            "embarrassed",
            "determined",
            "worried",
            "sleepy",
        ]:
            raw = f"<scene><character>aoi</character><expression>{expr}</expression><dialog_jp>テスト</dialog_jp><dialog_jp_furigana>テスト</dialog_jp_furigana><dialog_de>Test</dialog_de></scene>"
            result = ResponseParser.parse_scene(raw)
            assert result.expression == expr, f"Expression {expr} should be valid for aoi"
            assert result.parse_errors == []

    def test_no_scene_tag(self):
        raw = "Ich bin ein freier Text ohne XML."
        result = ResponseParser.parse_scene(raw)
        assert result.dialog_jp == raw
        assert result.dialog_de == ""
        assert result.character is None
        assert len(result.parse_errors) > 0

    def test_empty_response(self):
        result = ResponseParser.parse_scene("")
        assert result.parse_errors == ["Empty response from Claude"]

    def test_character_id_normalization(self):
        raw = "<scene><character>Aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.character == "aoi"

    def test_japanese_unicode_preserved(self):
        raw = "<scene><character>aoi</character><expression>excited</expression><background>apartment_room</background><dialog_jp>私の名前はあおいです！よろしくね～</dialog_jp><dialog_de>Mein Name ist Aoi! Freut mich!</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert "あおい" in result.dialog_jp
        assert "～" in result.dialog_jp

    def test_html_entities(self):
        raw = "<scene><character>aoi</character><expression>neutral</expression><dialog_jp>A &amp; B</dialog_jp><dialog_de>A &amp; B</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.dialog_jp == "A & B"
        assert result.dialog_de == "A & B"

    def test_multiple_scene_tags_takes_first(self):
        raw = "<scene><character>aoi</character><expression>happy</expression><dialog_jp>最初</dialog_jp><dialog_de>Erste</dialog_de></scene><scene><character>aoi</character><expression>neutral</expression><dialog_jp>二番目</dialog_jp><dialog_de>Zweite</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.dialog_jp == "最初"

    def test_no_character(self):
        raw = "<scene><expression>neutral</expression><background>apartment_room</background><dialog_jp>ナレーション</dialog_jp><dialog_de>Erzählung</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.character is None
        assert result.background == "apartment_room"

    def test_furigana_field_parsed(self):
        raw = "<scene><character>aoi</character><expression>talking</expression><background>cafe_shimokitazawa</background><dialog_jp>私は林です。</dialog_jp><dialog_jp_furigana>私[わたし]は林[はやし]です。</dialog_jp_furigana><dialog_de>Ich bin Hayashi.</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.dialog_jp == "私は林です。"
        assert result.dialog_jp_furigana == "私[わたし]は林[はやし]です。"
        assert "[わたし]" in result.dialog_jp_furigana

    def test_furigana_field_missing_falls_back_to_dialog_jp(self):
        raw = "<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.dialog_jp_furigana == "テスト"
        assert any("Missing dialog_jp_furigana" in e for e in result.parse_errors)

    def test_unknown_expression_unknown_character(self):
        raw = "<scene><character>unknown_npc</character><expression>bizarre</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.expression == "neutral"
        assert len(result.parse_errors) > 0

    def test_narrator_empty_character(self):
        raw = "<scene><character></character><background>shimokitazawa_station</background><dialog_jp>下北沢駅。</dialog_jp><dialog_jp_furigana>下北沢[しもきたざわ]駅[えき]。</dialog_jp_furigana><dialog_de>Bahnhof Shimokitazawa.</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.character is None
        assert result.background == "shimokitazawa_station"
        assert result.dialog_jp == "下北沢駅。"
        assert result.dialog_jp_furigana == "下北沢[しもきたざわ]駅[えき]。"
        assert result.parse_errors == []

    def test_narrator_no_character_tag(self):
        raw = "<scene><background>park</background><dialog_jp>公園に到着した。</dialog_jp><dialog_de>Im Park angekommen.</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.character is None
        assert result.background == "park"

    def test_no_analysis_returns_none(self):
        raw = "<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.analysis is None
        assert result.scene_status is None


class TestParseAnalysis:
    def test_parse_analysis_block(self):
        raw = """<scene><character>aoi</character><expression>happy</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>
<analysis>
  <grammar_topic>te_form</grammar_topic>
  <mastery_delta>+0.1</mastery_delta>
  <error_correction>Use ている not てある for ongoing actions</error_correction>
  <affection_language_effort>+2</affection_language_effort>
  <affection_cultural_interest>0</affection_cultural_interest>
  <affection_personal_bond>+1</affection_personal_bond>
  <affection_humor>0</affection_humor>
  <affection_reliability>0</affection_reliability>
</analysis>"""
        result = ResponseParser.parse_scene(raw)
        assert result.analysis is not None
        assert result.analysis.grammar_topic == "te_form"
        assert result.analysis.mastery_delta == pytest.approx(0.1)
        assert result.analysis.error_correction == "Use ている not てある for ongoing actions"
        assert result.analysis.affection_deltas["language_effort"] == 2.0
        assert result.analysis.affection_deltas["personal_bond"] == 1.0
        # Zero values should not be in deltas
        assert "cultural_interest" not in result.analysis.affection_deltas
        assert "humor" not in result.analysis.affection_deltas

    def test_analysis_without_grammar_topic(self):
        raw = """<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>
<analysis>
  <affection_language_effort>+3</affection_language_effort>
  <affection_humor>+1</affection_humor>
</analysis>"""
        result = ResponseParser.parse_scene(raw)
        assert result.analysis is not None
        assert result.analysis.grammar_topic is None
        assert result.analysis.mastery_delta == 0.0
        assert result.analysis.affection_deltas["language_effort"] == 3.0
        assert result.analysis.affection_deltas["humor"] == 1.0

    def test_negative_mastery_delta(self):
        raw = """<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>
<analysis>
  <grammar_topic>particles</grammar_topic>
  <mastery_delta>-0.05</mastery_delta>
</analysis>"""
        result = ResponseParser.parse_scene(raw)
        assert result.analysis.mastery_delta == pytest.approx(-0.05)

    def test_missing_analysis_returns_none(self):
        raw = "<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.analysis is None


class TestParseSceneStatus:
    def test_parse_scene_status(self):
        raw = """<scene><character>aoi</character><expression>happy</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>
<scene_status>
  <time_update>+1h</time_update>
  <scene_end>true</scene_end>
  <suggested_next>cafe_shimokitazawa|shrine_visit</suggested_next>
</scene_status>"""
        result = ResponseParser.parse_scene(raw)
        assert result.scene_status is not None
        assert result.scene_status.time_update == "+1h"
        assert result.scene_status.scene_end is True
        assert result.scene_status.suggested_next == ["cafe_shimokitazawa", "shrine_visit"]

    def test_scene_status_no_end(self):
        raw = """<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>
<scene_status>
  <time_update>+2h</time_update>
  <scene_end>false</scene_end>
</scene_status>"""
        result = ResponseParser.parse_scene(raw)
        assert result.scene_status is not None
        assert result.scene_status.time_update == "+2h"
        assert result.scene_status.scene_end is False
        assert result.scene_status.suggested_next == []

    def test_scene_status_next_day(self):
        raw = """<scene><character>aoi</character><expression>sleepy</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>
<scene_status>
  <time_update>next_day</time_update>
  <scene_end>true</scene_end>
  <suggested_next>morning_routine|explore_neighborhood</suggested_next>
</scene_status>"""
        result = ResponseParser.parse_scene(raw)
        assert result.scene_status.time_update == "next_day"
        assert result.scene_status.scene_end is True
        assert len(result.scene_status.suggested_next) == 2

    def test_missing_scene_status_returns_none(self):
        raw = "<scene><character>aoi</character><expression>neutral</expression><dialog_jp>テスト</dialog_jp><dialog_de>Test</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert result.scene_status is None

    def test_full_response_with_all_blocks(self):
        raw = """<scene>
  <character>aoi</character>
  <expression>excited</expression>
  <background>cafe_shimokitazawa</background>
  <dialog_jp>すごい！よく頑張ったね！</dialog_jp>
  <dialog_jp_furigana>すごい！よく頑張[がんば]ったね！</dialog_jp_furigana>
  <dialog_de>Toll! Du hast dich wirklich angestrengt!</dialog_de>
</scene>
<analysis>
  <grammar_topic>te_form</grammar_topic>
  <mastery_delta>+0.15</mastery_delta>
  <affection_language_effort>+3</affection_language_effort>
  <affection_personal_bond>+1</affection_personal_bond>
</analysis>
<scene_status>
  <time_update>+1h</time_update>
  <scene_end>false</scene_end>
</scene_status>"""
        result = ResponseParser.parse_scene(raw)
        # Scene
        assert result.character == "aoi"
        assert result.expression == "excited"
        assert result.background == "cafe_shimokitazawa"
        assert "頑張" in result.dialog_jp
        # Analysis
        assert result.analysis is not None
        assert result.analysis.grammar_topic == "te_form"
        assert result.analysis.mastery_delta == pytest.approx(0.15)
        assert result.analysis.affection_deltas["language_effort"] == 3.0
        # Scene Status
        assert result.scene_status is not None
        assert result.scene_status.time_update == "+1h"
        assert result.scene_status.scene_end is False


class TestFixReversedFurigana:
    def test_reversed_single(self):
        """のど[喉] → 喉[のど]"""
        assert _fix_reversed_furigana("のど[喉]が") == "喉[のど]が"

    def test_reversed_at_start(self):
        """Reversed at the start of a string"""
        result = _fix_reversed_furigana("かわ[渇]いた")
        assert result == "渇[かわ]いた"

    def test_correct_not_changed(self):
        """Already correct: 漢字[かんじ] stays as-is"""
        text = "下北沢[しもきたざわ]の駅[えき]で会[あ]いましょう"
        assert _fix_reversed_furigana(text) == text

    def test_empty_string(self):
        assert _fix_reversed_furigana("") == ""

    def test_no_furigana(self):
        text = "テストです"
        assert _fix_reversed_furigana(text) == text

    def test_correct_kanji_kana_untouched(self):
        """Correct notation 漢字[かんじ] must remain untouched"""
        text = "頑張[がんば]ったね"
        assert _fix_reversed_furigana(text) == text

    def test_mixed_kanji_hiragana_before_bracket(self):
        """お願い[おねがい] — mixed kanji+hiragana before bracket is correct"""
        text = "お願い[おねがい]します"
        assert _fix_reversed_furigana(text) == text

    def test_mixed_kanji_hiragana_complex(self):
        """Multiple mixed patterns in one string"""
        text = "お願い[おねがい]します。お元気[げんき]ですか？"
        assert _fix_reversed_furigana(text) == text

    def test_parse_scene_fixes_reversed(self):
        """Integration: reversed furigana gets fixed during parse"""
        raw = "<scene><character>aoi</character><expression>happy</expression><dialog_jp>喉が渇いた</dialog_jp><dialog_jp_furigana>のど[喉]が渇[かわ]いた</dialog_jp_furigana><dialog_de>Ich habe Durst.</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        # のど[喉] should be fixed to 喉[のど], 渇[かわ] is already correct
        assert "喉[のど]" in result.dialog_jp_furigana
        assert "渇[かわ]" in result.dialog_jp_furigana
        assert any("reversed" in e.lower() for e in result.parse_errors)

    def test_parse_scene_no_error_when_correct(self):
        """No error when furigana is already correct"""
        raw = "<scene><character>aoi</character><expression>happy</expression><dialog_jp>喉が渇いた</dialog_jp><dialog_jp_furigana>喉[のど]が渇[かわ]いた</dialog_jp_furigana><dialog_de>Ich habe Durst.</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert not any("reversed" in e.lower() for e in result.parse_errors)

    def test_fullwidth_brackets_normalized(self):
        """Fullwidth brackets ［ ］ should be normalized to halfwidth [ ]"""
        raw = "<scene><character>aoi</character><expression>happy</expression><dialog_jp>下北沢の駅で会いましょう</dialog_jp><dialog_jp_furigana>下北沢［しもきたざわ］の駅［えき］で会［あ］いましょう</dialog_jp_furigana><dialog_de>Treffen wir uns am Bahnhof Shimokitazawa.</dialog_de></scene>"
        result = ResponseParser.parse_scene(raw)
        assert "下北沢[しもきたざわ]" in result.dialog_jp_furigana
        assert "駅[えき]" in result.dialog_jp_furigana
        assert "会[あ]" in result.dialog_jp_furigana
        # No fullwidth brackets should remain
        assert "\uff3b" not in result.dialog_jp_furigana
        assert "\uff3d" not in result.dialog_jp_furigana


class TestKatakanaKanjiCompounds:
    """Tests for ヶ/ヵ and 〆 — characters that function like kanji in compounds."""

    def test_is_kanji_includes_ke(self):
        """ヶ (U+30F6) should be treated as kanji-like"""
        assert _is_kanji("\u30f6")  # ヶ
        assert _is_kanji("一ヶ月")

    def test_is_kanji_includes_ka(self):
        """ヵ (U+30F5) should be treated as kanji-like"""
        assert _is_kanji("\u30f5")  # ヵ
        assert _is_kanji("一ヵ所")

    def test_is_kanji_includes_shime(self):
        """〆 (U+3006) should be treated as kanji-like"""
        assert _is_kanji("\u3006")  # 〆
        assert _is_kanji("〆切")

    def test_has_kanji_includes_ke(self):
        """_has_kanji detects ヶ"""
        assert _has_kanji("一ヶ月")

    def test_reversed_furigana_with_ke(self):
        """Reversed furigana with ヶ compound: いっかげつ[一ヶ月] → 一ヶ月[いっかげつ]"""
        result = _fix_reversed_furigana("いっかげつ[一ヶ月]")
        assert result == "一ヶ月[いっかげつ]"

    def test_reversed_furigana_with_shime(self):
        """Reversed furigana with 〆: しめきり[〆切] → 〆切[しめきり]"""
        result = _fix_reversed_furigana("しめきり[〆切]")
        assert result == "〆切[しめきり]"

    def test_correct_ke_not_changed(self):
        """Already correct: 一ヶ月[いっかげつ] stays as-is"""
        text = "一ヶ月[いっかげつ]"
        assert _fix_reversed_furigana(text) == text

    def test_correct_shime_not_changed(self):
        """Already correct: 〆切[しめきり] stays as-is"""
        text = "〆切[しめきり]"
        assert _fix_reversed_furigana(text) == text
