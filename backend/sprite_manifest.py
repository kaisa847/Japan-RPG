"""Layered sprite manifests ("Baukasten").

A character with a ``manifest.json`` in its asset folder is rendered as
two stacked layers: a pose body plus a face patch overlaid at a fixed
anchor. This turns P poses x F faces into P+F assets instead of P*F
full sprites and guarantees the face stays pixel-aligned per pose.

Directory layout (per character, e.g. assets/characters/aoi/):
    manifest.json
    poses/<pose_id>.png       full-body art WITHOUT facial features
    faces/<face_id>.png       face patch, overlaid at the pose anchor
    <expression>.png          legacy single-file sprites (fallback)

Manifest schema (version 1):
    {
      "version": 1,
      "default_pose": "stand",
      "default_face": "neutral",
      "blink_face": "blink",              // optional, enables blinking
      "poses": {
        "stand": {
          "body": "poses/stand.png",
          // face anchor, relative to the body image dimensions:
          // x/y = center of the face patch, w = patch width
          "anchor": { "x": 0.5, "y": 0.15, "w": 0.35 }
        }
      },
      "faces": ["neutral", "happy", ...],
      // optional: face ids that have a faces/<id>_talk.png variant for
      // the lip-flap animation while dialog text is typing
      "talk_faces": ["neutral", "happy", ...],
      // optional: per-outfit pose bodies; faces are shared across outfits
      "outfits": {
        "yukata": { "poses": { "stand": { "body": "poses/yukata/stand.png",
                                           "anchor": { ... } } } }
      }
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SpriteManifests:
    """Loads and serves per-character layered sprite manifests."""

    def __init__(self, assets_dir: str = "assets"):
        self.assets_dir = Path(assets_dir)
        self.manifests: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        self.manifests = {}
        char_root = self.assets_dir / "characters"
        if not char_root.exists():
            return
        for char_dir in char_root.iterdir():
            manifest_path = char_dir / "manifest.json"
            if not char_dir.is_dir() or not manifest_path.exists():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Invalid sprite manifest %s: %s", manifest_path, e)
                continue
            manifest = self._validate(raw, char_dir.name)
            if manifest:
                self.manifests[char_dir.name] = manifest
                logger.info(
                    "Sprite manifest loaded: %s (%d poses, %d faces)",
                    char_dir.name, len(manifest["poses"]), len(manifest["faces"]),
                )

    @staticmethod
    def _clean_pose_table(poses: dict, char_id: str) -> dict[str, dict]:
        clean: dict[str, dict] = {}
        for pose_id, pose in poses.items():
            if not isinstance(pose, dict) or not pose.get("body"):
                logger.warning("Manifest %s: pose %r invalid, skipping", char_id, pose_id)
                continue
            anchor = pose.get("anchor") or {}
            try:
                clean_anchor = {
                    "x": float(anchor.get("x", 0.5)),
                    "y": float(anchor.get("y", 0.15)),
                    "w": float(anchor.get("w", 0.35)),
                }
            except (TypeError, ValueError):
                clean_anchor = {"x": 0.5, "y": 0.15, "w": 0.35}
            clean[pose_id] = {"body": pose["body"], "anchor": clean_anchor}
        return clean

    @classmethod
    def _validate(cls, raw: dict, char_id: str) -> dict | None:
        poses = raw.get("poses")
        faces = raw.get("faces")
        if not isinstance(poses, dict) or not poses:
            logger.warning("Manifest %s: no poses, ignoring", char_id)
            return None
        if not isinstance(faces, list) or not faces:
            logger.warning("Manifest %s: no faces, ignoring", char_id)
            return None

        clean_poses = cls._clean_pose_table(poses, char_id)
        if not clean_poses:
            return None

        default_pose = raw.get("default_pose")
        if default_pose not in clean_poses:
            default_pose = next(iter(clean_poses))

        default_face = raw.get("default_face")
        if default_face not in faces:
            default_face = faces[0]

        blink_face = raw.get("blink_face")
        if blink_face is not None and blink_face not in faces:
            blink_face = None

        talk_faces = [
            f for f in (raw.get("talk_faces") or [])
            if isinstance(f, str) and f in faces
        ]

        # Faces with (half-)closed eyes by design: blinking is skipped there
        no_blink_faces = [
            f for f in (raw.get("no_blink_faces") or [])
            if isinstance(f, str) and f in faces
        ]

        outfits: dict[str, dict] = {}
        raw_outfits = raw.get("outfits")
        if isinstance(raw_outfits, dict):
            for outfit_id, outfit in raw_outfits.items():
                if not isinstance(outfit, dict):
                    continue
                outfit_poses = cls._clean_pose_table(
                    outfit.get("poses") or {}, f"{char_id}/{outfit_id}"
                )
                if outfit_poses:
                    outfits[outfit_id] = {"poses": outfit_poses}

        return {
            "version": 1,
            "default_pose": default_pose,
            "default_face": default_face,
            "blink_face": blink_face,
            "poses": clean_poses,
            "faces": list(faces),
            "talk_faces": talk_faces,
            "no_blink_faces": no_blink_faces,
            "outfits": outfits,
        }

    # --- Queries ---

    def has_manifest(self, char_id: str) -> bool:
        return char_id in self.manifests

    def get(self, char_id: str) -> dict | None:
        return self.manifests.get(char_id)

    def pose_ids(self, char_id: str) -> list[str]:
        m = self.manifests.get(char_id)
        return sorted(m["poses"].keys()) if m else []

    def validate_pose(self, char_id: str, pose: str | None) -> str | None:
        """Return the pose if it exists for this character, else None."""
        if not pose:
            return None
        m = self.manifests.get(char_id or "")
        if m and pose in m["poses"]:
            return pose
        return None

    def outfit_ids(self, char_id: str) -> list[str]:
        """Outfits with layered bodies, 'standard' always first."""
        m = self.manifests.get(char_id or "")
        if not m or not m.get("outfits"):
            return []
        return ["standard"] + sorted(m["outfits"].keys())

    def validate_outfit(self, char_id: str, outfit: str | None) -> str | None:
        """Return the outfit if it exists for this character, else None
        ('standard' is always valid when a manifest exists)."""
        if not outfit:
            return None
        m = self.manifests.get(char_id or "")
        if not m:
            return None
        if outfit == "standard" or outfit in (m.get("outfits") or {}):
            return outfit
        return None

    def to_api_dict(self) -> dict:
        """Manifests as served to the frontend."""
        return self.manifests
