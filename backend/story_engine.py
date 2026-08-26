"""Story beat engine: selects the active scripted beat for a game state.

Beats are defined in ``data/story/beats.json``. At most ONE beat is
active at a time; only its short director's note is injected into the
system prompt, keeping the per-request token cost minimal.

A beat completes when Claude reports the beat's flag via
``<story_flag>`` in ``scene_status``. Only the active beat's flag is
accepted, so the story cannot be skipped ahead.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class BeatTrigger(BaseModel):
    min_day: int = 1
    min_score: float = 0.0
    required_flags: list[str] = []


class StoryBeat(BaseModel):
    id: str
    title: str = ""
    trigger: BeatTrigger = Field(default_factory=BeatTrigger)
    sets_flag: str = ""
    direction: str = ""
    location_hint: Optional[str] = None
    didactic_hint: Optional[str] = None


class StoryEngine:
    def __init__(self, data_dir: str = "data"):
        self.beats: list[StoryBeat] = []
        beats_path = Path(data_dir) / "story" / "beats.json"
        if not beats_path.exists():
            logger.warning("Story beats file not found: %s", beats_path)
            return
        try:
            raw = json.loads(beats_path.read_text(encoding="utf-8"))
            self.beats = [StoryBeat.model_validate(b) for b in raw.get("beats", [])]
            logger.info("Loaded %d story beats", len(self.beats))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to load story beats: %s", e)

    def select_beat(
        self,
        day: int,
        score: float,
        flags: dict[str, bool],
        completed_beats: list[str],
    ) -> Optional[StoryBeat]:
        """Return the first eligible beat, in file order, or None.

        Eligible = not completed, day/score thresholds met, all
        required flags set.
        """
        for beat in self.beats:
            if beat.id in completed_beats:
                continue
            t = beat.trigger
            if day < t.min_day:
                continue
            if score < t.min_score:
                continue
            if any(not flags.get(f, False) for f in t.required_flags):
                continue
            return beat
        return None

    def get_beat(self, beat_id: str) -> Optional[StoryBeat]:
        for beat in self.beats:
            if beat.id == beat_id:
                return beat
        return None

    def build_prompt_block(self, beat: StoryBeat, player_name: str) -> str:
        """Render the active beat as a compact system prompt block."""
        lines = [
            "AKTUELLER STORY-BEAT (natürlich einweben, NICHT erzwingen — "
            "wenn der Spieler das Thema wechselt, versuche es in einer "
            "späteren Szene erneut):",
            beat.direction.replace("{player_name}", player_name),
        ]
        if beat.location_hint:
            lines.append(f"Passender Ort dafür: {beat.location_hint}")
        if beat.didactic_hint:
            lines.append(f"Sprachlicher Fokus dabei: {beat.didactic_hint}")
        lines.append(
            f"Sobald dieser Beat im Dialog tatsächlich stattgefunden hat, "
            f"melde ihn mit <story_flag>{beat.sets_flag}</story_flag> im scene_status."
        )
        return "\n".join(lines)
