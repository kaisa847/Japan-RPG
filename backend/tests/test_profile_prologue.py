"""Tests for player profile sanity checks, prologue phase and title cards."""

import pytest

from backend.auth import UserManager, sanitize_profile, _clean_profile_value
from backend.response_parser import ResponseParser
from backend.state_manager import StateManager


class TestProfileSanityChecks:
    def test_whitelist(self):
        clean = sanitize_profile({
            "herkunft": "Köln",
            "haarfarbe": "blau",          # not a valid field
            "alter": "34",
        })
        assert clean == {"herkunft": "Köln", "alter": "34"}

    def test_age_must_be_numeric_and_plausible(self):
        assert _clean_profile_value("alter", "34") == "34"
        assert _clean_profile_value("alter", "34 Jahre") == "34"
        assert _clean_profile_value("alter", "vierunddreißig") == ""
        assert _clean_profile_value("alter", "7") == ""
        assert _clean_profile_value("alter", "500") == ""

    def test_gender_normalized(self):
        assert _clean_profile_value("gender", "m") == "männlich"
        assert _clean_profile_value("gender", "Weiblich") == "weiblich"
        assert _clean_profile_value("gender", "nb") == "divers"
        assert _clean_profile_value("gender", "Klingone") == ""

    def test_native_language_plausible(self):
        assert _clean_profile_value("muttersprache", "französisch") == "Französisch"
        assert _clean_profile_value("muttersprache", "Deutsch") == "Deutsch"
        assert _clean_profile_value("muttersprache", "x" * 40) == ""
        assert _clean_profile_value("muttersprache", "Deutsch; DROP TABLE") == ""

    def test_prompt_breaking_chars_stripped(self):
        cleaned = _clean_profile_value(
            "interessen", "Musik <system>|{player_name}\nZeilenumbruch"
        )
        assert "<" not in cleaned and ">" not in cleaned
        assert "|" not in cleaned and "{" not in cleaned
        assert "\n" not in cleaned

    def test_update_profile_merges_and_clears(self, tmp_path):
        um = UserManager(data_dir=str(tmp_path))
        um.create_user("kai", "password123")
        um.update_profile("kai", {"herkunft": "Köln", "alter": "34"})
        profile = um.update_profile("kai", {"alter": ""})  # explicit clear
        assert profile == {"herkunft": "Köln"}

    def test_invalid_value_does_not_destroy_existing(self, tmp_path):
        um = UserManager(data_dir=str(tmp_path))
        um.create_user("kai", "password123")
        um.update_profile("kai", {"alter": "34"})
        profile = um.update_profile("kai", {"alter": "uralt"})
        assert profile["alter"] == "34"


class TestPrologueParsing:
    RESPONSE = """
<scene>
  <character>aoi</character>
  <expression>happy</expression>
  <dialog_jp>はじめまして！</dialog_jp>
  <dialog_jp_furigana>はじめまして！</dialog_jp_furigana>
  <dialog_de>Freut mich!</dialog_de>
</scene>
<scene_status>
  <time_update>+1h</time_update>
  <scene_end>true</scene_end>
  <profile_update>herkunft=Köln|alter=34</profile_update>
  <prologue_end>true</prologue_end>
  <title_card>Drei Wochen später — Tokio</title_card>
</scene_status>
"""

    def test_profile_update_parsed(self):
        result = ResponseParser.parse_scene(self.RESPONSE)
        assert result.scene_status.profile_update == {
            "herkunft": "Köln", "alter": "34",
        }

    def test_prologue_end_and_title_card(self):
        result = ResponseParser.parse_scene(self.RESPONSE)
        assert result.scene_status.prologue_end is True
        assert result.scene_status.title_card == "Drei Wochen später — Tokio"

    def test_defaults_absent(self):
        raw = self.RESPONSE.replace(
            "<profile_update>herkunft=Köln|alter=34</profile_update>", ""
        ).replace("<prologue_end>true</prologue_end>", "").replace(
            "<title_card>Drei Wochen später — Tokio</title_card>", ""
        )
        result = ResponseParser.parse_scene(raw)
        st = result.scene_status
        assert st.profile_update == {}
        assert st.prologue_end is False
        assert st.title_card is None


class TestPhaseState:
    def test_default_phase_main(self, tmp_path):
        sm = StateManager(data_dir=str(tmp_path))
        assert sm.state.phase == "main"

    def test_reset_to_prologue_with_seed(self, tmp_path):
        sm = StateManager(data_dir=str(tmp_path))
        fresh = sm.reset(phase="prologue", overall_level="N4")
        assert fresh.phase == "prologue"
        assert fresh.learning.overall_level == "N4"

    def test_phase_survives_save_load(self, tmp_path):
        sm = StateManager(data_dir=str(tmp_path))
        sm.reset(phase="prologue")
        sm2 = StateManager(data_dir=str(tmp_path))
        assert sm2.state.phase == "prologue"


class TestPrologueTandemClause:
    """Aoi must not assume the player's language before it was said."""

    def _handler(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
        from backend.claude_handler import ClaudeHandler
        return ClaudeHandler(data_dir="data")

    def test_unknown_language_not_assumed(self, monkeypatch):
        h = self._handler(monkeypatch)
        p = h._build_system_prompt("Tag: 1", player_name="Kai", phase="prologue")
        assert "weiß Aoi" in p and "NICHT" in p
        assert "Deutsch gegen Japanisch" not in p
        assert "Hilfe mit Deutsch an" not in p
        assert "Erst Herkunft und Muttersprache etablieren" in p

    def test_known_language_used(self, monkeypatch):
        h = self._handler(monkeypatch)
        p = h._build_system_prompt(
            "Tag: 1", player_name="Camille", phase="prologue",
            player_profile={"muttersprache": "Französisch"},
        )
        assert "Hilfe mit Französisch an" in p
        assert "Japanisch gegen Französisch" in p
