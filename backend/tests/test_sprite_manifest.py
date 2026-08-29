"""Tests for layered sprite manifests and pose/staging parsing."""

import json

import pytest

from backend.response_parser import ResponseParser
from backend.sprite_manifest import SpriteManifests


@pytest.fixture
def assets_dir(tmp_path):
    char_dir = tmp_path / "characters" / "aoi"
    char_dir.mkdir(parents=True)
    manifest = {
        "version": 1,
        "default_pose": "stand",
        "default_face": "neutral",
        "blink_face": "blink",
        "poses": {
            "stand": {"body": "poses/stand.png", "anchor": {"x": 0.5, "y": 0.15, "w": 0.375}},
            "wave": {"body": "poses/wave.png", "anchor": {"x": 0.5, "y": 0.15, "w": 0.375}},
        },
        "faces": ["neutral", "happy", "blink"],
    }
    (char_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return tmp_path


class TestSpriteManifests:
    def test_loads_manifest(self, assets_dir):
        sm = SpriteManifests(assets_dir=str(assets_dir))
        assert sm.has_manifest("aoi")
        assert sm.pose_ids("aoi") == ["stand", "wave"]

    def test_missing_assets_dir(self, tmp_path):
        sm = SpriteManifests(assets_dir=str(tmp_path / "nope"))
        assert sm.manifests == {}
        assert sm.pose_ids("aoi") == []

    def test_character_without_manifest_ignored(self, assets_dir):
        (assets_dir / "characters" / "tanaka").mkdir()
        sm = SpriteManifests(assets_dir=str(assets_dir))
        assert not sm.has_manifest("tanaka")

    def test_invalid_json_ignored(self, assets_dir):
        bad = assets_dir / "characters" / "bad"
        bad.mkdir()
        (bad / "manifest.json").write_text("{kaputt", encoding="utf-8")
        sm = SpriteManifests(assets_dir=str(assets_dir))
        assert not sm.has_manifest("bad")
        assert sm.has_manifest("aoi")

    def test_validate_pose(self, assets_dir):
        sm = SpriteManifests(assets_dir=str(assets_dir))
        assert sm.validate_pose("aoi", "wave") == "wave"
        assert sm.validate_pose("aoi", "backflip") is None
        assert sm.validate_pose("aoi", None) is None
        assert sm.validate_pose("unknown_char", "stand") is None

    def test_defaults_fixed_up(self, tmp_path):
        char_dir = tmp_path / "characters" / "x"
        char_dir.mkdir(parents=True)
        manifest = {
            "default_pose": "does_not_exist",
            "default_face": "also_missing",
            "blink_face": "nope",
            "poses": {"sit": {"body": "poses/sit.png"}},
            "faces": ["calm"],
        }
        (char_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        sm = SpriteManifests(assets_dir=str(tmp_path))
        m = sm.get("x")
        assert m["default_pose"] == "sit"
        assert m["default_face"] == "calm"
        assert m["blink_face"] is None
        # Missing anchor gets defaults
        assert m["poses"]["sit"]["anchor"] == {"x": 0.5, "y": 0.15, "w": 0.35}

    def test_manifest_without_poses_rejected(self, tmp_path):
        char_dir = tmp_path / "characters" / "y"
        char_dir.mkdir(parents=True)
        (char_dir / "manifest.json").write_text(
            json.dumps({"poses": {}, "faces": ["neutral"]}), encoding="utf-8"
        )
        sm = SpriteManifests(assets_dir=str(tmp_path))
        assert not sm.has_manifest("y")


class TestPoseStagingParsing:
    RESPONSE = """
<scene>
  <character>aoi</character>
  <expression>happy</expression>
  <pose>Wave</pose>
  <staging>right near</staging>
  <background>park</background>
  <dialog_jp>ほら、見て！</dialog_jp>
  <dialog_jp_furigana>ほら、見[み]て！</dialog_jp_furigana>
  <dialog_de>Schau mal!</dialog_de>
</scene>
"""

    def test_pose_parsed_and_normalized(self):
        result = ResponseParser.parse_scene(self.RESPONSE)
        assert result.pose == "wave"

    def test_staging_parsed(self):
        result = ResponseParser.parse_scene(self.RESPONSE)
        assert result.staging == ["right", "near"]

    def test_unknown_staging_tokens_dropped(self):
        response = self.RESPONSE.replace(
            "<staging>right near</staging>",
            "<staging>right upside_down near</staging>",
        )
        result = ResponseParser.parse_scene(response)
        assert result.staging == ["right", "near"]

    def test_missing_tags_default(self):
        response = self.RESPONSE.replace("<pose>Wave</pose>", "").replace(
            "<staging>right near</staging>", ""
        )
        result = ResponseParser.parse_scene(response)
        assert result.pose is None
        assert result.staging == []
