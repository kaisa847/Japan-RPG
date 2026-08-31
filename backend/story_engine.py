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


# JLPT ordering for min_level triggers
LEVEL_ORDER = {"N5": 0, "N4": 1, "N3": 2, "N2": 3, "N1": 4}


class BeatTrigger(BaseModel):
    min_day: int = 1
    min_score: float = 0.0
    required_flags: list[str] = []
    forbidden_flags: list[str] = []
    # Learning-based triggers ("gates forgive, endings judge"):
    # hard learning gates should only be used on bonus/ending beats.
    min_vocab: int = 0
    min_topics_mastered: int = 0
    min_level: Optional[str] = None


class StoryBeat(BaseModel):
    id: str
    title: str = ""
    type: str = "main"          # main | bonus | ending
    priority: int = 0           # endings: highest eligible priority wins
    trigger: BeatTrigger = Field(default_factory=BeatTrigger)
    sets_flag: str = ""
    direction: str = ""
    location_hint: Optional[str] = None
    didactic_hint: Optional[str] = None
    epilogue: Optional[str] = None   # endings: recap-screen text


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
        vocab_count: int = 0,
        topics_mastered: int = 0,
        level: str = "N5",
    ) -> Optional[StoryBeat]:
        """Return the active beat, or None.

        Ending beats take precedence and are chosen by highest eligible
        priority (deterministic ending selection); everything else runs
        in file order (main arc first, learning-gated bonus beats fill
        the gaps).
        """
        eligible = [
            b for b in self.beats
            if self._is_eligible(
                b, day, score, flags, completed_beats,
                vocab_count, topics_mastered, level,
            )
        ]
        endings = [b for b in eligible if b.type == "ending"]
        if endings:
            return max(endings, key=lambda b: b.priority)
        return eligible[0] if eligible else None

    @staticmethod
    def _is_eligible(
        beat: StoryBeat,
        day: int,
        score: float,
        flags: dict[str, bool],
        completed_beats: list[str],
        vocab_count: int,
        topics_mastered: int,
        level: str,
    ) -> bool:
        if beat.id in completed_beats:
            return False
        t = beat.trigger
        if day < t.min_day or score < t.min_score:
            return False
        if any(not flags.get(f, False) for f in t.required_flags):
            return False
        if any(flags.get(f, False) for f in t.forbidden_flags):
            return False
        if vocab_count < t.min_vocab or topics_mastered < t.min_topics_mastered:
            return False
        if t.min_level is not None:
            if LEVEL_ORDER.get(level, 0) < LEVEL_ORDER.get(t.min_level, 0):
                return False
        return True

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
