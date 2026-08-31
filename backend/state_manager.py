"""Game state management with JSON persistence."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backend.grammar_taxonomy import estimate_jlpt, normalize_topic

logger = logging.getLogger(__name__)

MAX_SCENE_HISTORY = 100
# Long-term memory: rolling list of short scene summaries
MAX_MEMORIES = 12
MAX_MEMORY_CHARS = 240
# Vocabulary notebook limits
MAX_VOCAB_ENTRIES = 300
VOCAB_STRENGTH_INITIAL = 0.1
VOCAB_STRENGTH_INCREMENT = 0.15
VOCAB_DUE_THRESHOLD = 0.8
# Open promises (appointments etc.) tracked for the reliability factor
MAX_OPEN_PROMISES = 3

# --- Time helpers ---

TIME_PERIODS = {
    range(5, 9): "early_morning",
    range(9, 12): "morning",
    range(12, 14): "midday",
    range(14, 17): "afternoon",
    range(17, 20): "evening",
    range(20, 24): "night",
    range(0, 5): "late_night",
}


def _period_from_hour(hour: int) -> str:
    for hour_range, period in TIME_PERIODS.items():
        if hour in hour_range:
            return period
    return "afternoon"


# --- Data Models ---


class TopicMastery(BaseModel):
    topic: str = ""
    mastery: float = Field(default=0.0, ge=0.0, le=1.0)
    attempts: int = 0
    last_seen: str = ""


class VocabEntry(BaseModel):
    word: str = ""
    reading: str = ""
    meaning_de: str = ""
    strength: float = Field(default=VOCAB_STRENGTH_INITIAL, ge=0.0, le=1.0)
    times_seen: int = 1
    first_seen_day: int = 1
    last_seen_day: int = 1


class PlayerLearningProfile(BaseModel):
    overall_level: str = "N5"
    topics: dict[str, TopicMastery] = {}
    weak_points: list[str] = []
    total_interactions: int = 0
    vocab: dict[str, VocabEntry] = {}


class MemoryEntry(BaseModel):
    day: int = 1
    text: str = ""


class StoryState(BaseModel):
    completed_beats: list[str] = []


class Promise(BaseModel):
    text: str = ""
    created_day: int = 1


class AoiAffection(BaseModel):
    language_effort: float = Field(default=20.0, ge=0.0, le=100.0)
    cultural_interest: float = Field(default=20.0, ge=0.0, le=100.0)
    personal_bond: float = Field(default=20.0, ge=0.0, le=100.0)
    humor: float = Field(default=20.0, ge=0.0, le=100.0)
    reliability: float = Field(default=20.0, ge=0.0, le=100.0)

    @property
    def weighted_score(self) -> float:
        return (
            self.language_effort * 0.35
            + self.cultural_interest * 0.25
            + self.personal_bond * 0.20
            + self.humor * 0.10
            + self.reliability * 0.10
        )

    @property
    def tone(self) -> str:
        s = self.weighted_score
        if s >= 80:
            return "intimate"
        if s >= 60:
            return "warm"
        if s >= 40:
            return "friendly"
        if s >= 20:
            return "neutral"
        return "distant"

    def to_display_dict(self) -> dict:
        return {
            "language_effort": self.language_effort,
            "cultural_interest": self.cultural_interest,
            "personal_bond": self.personal_bond,
            "humor": self.humor,
            "reliability": self.reliability,
            "weighted_score": round(self.weighted_score, 1),
            "tone": self.tone,
        }


class TimeState(BaseModel):
    day: int = 1
    hour: int = 14
    period: str = "afternoon"

    def advance_hours(self, hours: int) -> None:
        self.hour += hours
        while self.hour >= 24:
            self.hour -= 24
            self.day += 1
        self.period = _period_from_hour(self.hour)

    def advance_to_next_day(self, start_hour: int = 9) -> None:
        self.day += 1
        self.hour = start_hour
        self.period = _period_from_hour(self.hour)


class GameState(BaseModel):
    # "prologue" = forum chat before arriving in Japan; "main" = the game.
    # Defaults to "main" so existing saves are unaffected.
    phase: str = "main"
    time: TimeState = TimeState()
    current_location: str = "apartment"
    current_background: str = "apartment"
    current_character: Optional[str] = "aoi"
    learning: PlayerLearningProfile = PlayerLearningProfile()
    affection: AoiAffection = AoiAffection()
    conversation_history: list[dict] = []
    scene_history: list[dict] = []
    last_scene: Optional[dict] = None
    flags: dict[str, bool] = {}
    memories: list[MemoryEntry] = []
    story: StoryState = Field(default_factory=StoryState)
    open_promises: list[Promise] = []
    last_updated: str = ""
    turns_since_time_advance: int = 0


class SaveSlotMeta(BaseModel):
    slot_id: int
    name: str = ""
    day_number: int = 1
    current_character: Optional[str] = None
    current_background: str = "apartment"
    saved_at: str = ""
    turn_count: int = 0


class SaveSlotData(BaseModel):
    meta: SaveSlotMeta
    state: GameState


class StateManager:
    STATE_FILE = "game_state.json"
    SESSION_LOG_FILE = "session_log.json"
    SAVES_DIR = "saves"
    # 8 exchanges of short-term context; long-term continuity comes from
    # the episodic memory summaries (cheaper in tokens than raw history).
    MAX_CONVERSATION_HISTORY = 16
    MAX_SAVE_SLOTS = 9

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_or_create()

    def _load_or_create(self) -> GameState:
        state_path = self.data_dir / self.STATE_FILE
        if state_path.exists():
            try:
                raw = state_path.read_text(encoding="utf-8")
                data = json.loads(raw)
                return GameState.model_validate(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Corrupt game state file, creating default: %s", e)
        return GameState()

    def save(self) -> None:
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        state_path = self.data_dir / self.STATE_FILE
        tmp_path = state_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                self.state.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(state_path)
        except OSError as e:
            logger.error("Failed to save game state: %s", e)
            if tmp_path.exists():
                tmp_path.unlink()

    def reset(self, phase: str = "main", overall_level: str | None = None) -> GameState:
        self._archive_session()
        self.state = GameState(phase=phase)
        if overall_level:
            self.state.learning.overall_level = overall_level
        self.save()
        return self.state

    def _archive_session(self) -> None:
        if not self.state.conversation_history:
            return
        log_path = self.data_dir / self.SESSION_LOG_FILE
        try:
            if log_path.exists():
                sessions = json.loads(log_path.read_text(encoding="utf-8"))
            else:
                sessions = []
            sessions.append({
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "day_number": self.state.time.day,
                "turns": len(self.state.conversation_history),
            })
            log_path.write_text(
                json.dumps(sessions, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to archive session: %s", e)

    def update_from_scene(self, scene_data: dict) -> None:
        if scene_data.get("background"):
            self.state.current_background = scene_data["background"]
        if scene_data.get("character"):
            self.state.current_character = scene_data["character"]

    def add_conversation_turn(self, role: str, content: str) -> None:
        self.state.conversation_history.append({
            "role": role,
            "content": content,
        })
        if len(self.state.conversation_history) > self.MAX_CONVERSATION_HISTORY:
            self.state.conversation_history = self.state.conversation_history[
                -self.MAX_CONVERSATION_HISTORY:
            ]

    def add_scene_to_history(self, scene: dict) -> None:
        """Append a rendered scene to the scene history (max MAX_SCENE_HISTORY)."""
        entry = {
            "character": scene.get("character"),
            "speaker": scene.get("speaker"),
            "expression": scene.get("expression", "neutral"),
            "pose": scene.get("pose"),
            "staging": scene.get("staging", []),
            "background": scene.get("background"),
            "dialog_jp": scene.get("dialog_jp", ""),
            "dialog_jp_furigana": scene.get("dialog_jp_furigana", ""),
            "dialog_de": scene.get("dialog_de", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.state.scene_history.append(entry)
        if len(self.state.scene_history) > MAX_SCENE_HISTORY:
            self.state.scene_history = self.state.scene_history[-MAX_SCENE_HISTORY:]

    # --- Learning & Affection Processing ---

    # Clamp raw affection deltas from Claude to this range before applying
    AFFECTION_DELTA_CLAMP = 1.0
    # Multiply clamped deltas by this factor for gradual progression
    AFFECTION_DAMPING = 0.5

    def process_analysis(self, analysis_data: dict | None) -> None:
        """Process analysis data from Claude to update learning and affection."""
        if not analysis_data:
            return

        self.state.learning.total_interactions += 1

        # Update topic mastery (canonical taxonomy only — free-form
        # topic names that don't match are dropped to avoid fragmenting
        # the mastery map)
        topic = normalize_topic(analysis_data.get("grammar_topic"))
        if topic:
            delta = analysis_data.get("mastery_delta", 0.0)
            if topic not in self.state.learning.topics:
                self.state.learning.topics[topic] = TopicMastery(topic=topic)
            tm = self.state.learning.topics[topic]
            tm.mastery = max(0.0, min(1.0, tm.mastery + delta))
            tm.attempts += 1
            tm.last_seen = datetime.now(timezone.utc).isoformat()
            # Re-derive the JLPT estimate from canonical mastery
            self.state.learning.overall_level = estimate_jlpt(
                self.state.learning.topics
            )

        # Update affection factors (clamped & damped)
        affection_fields = [
            "language_effort", "cultural_interest",
            "personal_bond", "humor", "reliability",
        ]
        affection_deltas = analysis_data.get("affection_deltas", {})
        for field in affection_fields:
            raw_delta = affection_deltas.get(field, 0.0)
            if raw_delta != 0:
                clamped = max(-self.AFFECTION_DELTA_CLAMP,
                              min(self.AFFECTION_DELTA_CLAMP, raw_delta))
                delta = clamped * self.AFFECTION_DAMPING
                current = getattr(self.state.affection, field)
                new_val = max(0.0, min(100.0, current + delta))
                setattr(self.state.affection, field, new_val)

        # Recalculate weak points
        self._update_weak_points()

    # Advance 1 hour automatically after this many turns without an explicit time_update
    PERIODIC_TIME_ADVANCE_TURNS = 6

    def process_time_update(self, time_update: str | None) -> None:
        """Process time update from scene_status (e.g. '+1h', '+3h', 'next_day')."""
        if not time_update:
            return
        time_update = time_update.strip().lower()
        if time_update == "next_day":
            self.state.time.advance_to_next_day()
        elif time_update.startswith("+") and time_update.endswith("h"):
            try:
                hours = int(time_update[1:-1])
                self.state.time.advance_hours(hours)
            except ValueError:
                logger.warning("Invalid time_update format: %s", time_update)
                return
        else:
            logger.warning("Unknown time_update format: %s", time_update)
            return
        # Reset the periodic counter on successful time advancement
        self.state.turns_since_time_advance = 0

    def maybe_advance_time_periodic(self) -> None:
        """Advance time by 1h if enough turns passed without an explicit time update."""
        self.state.turns_since_time_advance += 1
        if self.state.turns_since_time_advance >= self.PERIODIC_TIME_ADVANCE_TURNS:
            logger.info(
                "Periodic time advance after %d turns without explicit update",
                self.state.turns_since_time_advance,
            )
            self.state.time.advance_hours(1)
            self.state.turns_since_time_advance = 0

    # --- Episodic Memory ---

    def add_memory(self, text: str) -> None:
        """Store a short scene summary as long-term memory (rolling cap)."""
        text = (text or "").strip()
        if not text:
            return
        if len(text) > MAX_MEMORY_CHARS:
            text = text[: MAX_MEMORY_CHARS - 1].rstrip() + "…"
        self.state.memories.append(
            MemoryEntry(day=self.state.time.day, text=text)
        )
        if len(self.state.memories) > MAX_MEMORIES:
            self.state.memories = self.state.memories[-MAX_MEMORIES:]

    # --- Vocabulary Notebook ---

    def process_vocab(self, entries: list[dict]) -> None:
        """Register new/repeated vocabulary from a scene.

        Re-encountering a known word strengthens it — recycling due
        words through the dialog acts as hidden spaced repetition.
        """
        vocab = self.state.learning.vocab
        day = self.state.time.day
        for entry in entries:
            word = (entry.get("word") or "").strip()
            if not word:
                continue
            if word in vocab:
                v = vocab[word]
                v.strength = min(1.0, v.strength + VOCAB_STRENGTH_INCREMENT)
                v.times_seen += 1
                v.last_seen_day = day
                if entry.get("reading") and not v.reading:
                    v.reading = entry["reading"].strip()
                if entry.get("meaning_de") and not v.meaning_de:
                    v.meaning_de = entry["meaning_de"].strip()
                continue
            if len(vocab) >= MAX_VOCAB_ENTRIES:
                # Evict the strongest (= best learned) entry to make room
                strongest = max(vocab.values(), key=lambda v: v.strength)
                if strongest.strength < 0.9:
                    continue  # notebook full of unlearned words: skip new
                del vocab[strongest.word]
            vocab[word] = VocabEntry(
                word=word,
                reading=(entry.get("reading") or "").strip(),
                meaning_de=(entry.get("meaning_de") or "").strip(),
                first_seen_day=day,
                last_seen_day=day,
            )

    def get_due_vocab(self, limit: int = 5) -> list[VocabEntry]:
        """Weakest, longest-unseen words that should be recycled soon."""
        due = [
            v for v in self.state.learning.vocab.values()
            if v.strength < VOCAB_DUE_THRESHOLD
            and v.last_seen_day < self.state.time.day
        ]
        due.sort(key=lambda v: (v.strength, v.last_seen_day))
        return due[:limit]

    # --- Promises (reliability system) ---

    def add_promise(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Avoid duplicates of the same promise text
        if any(p.text == text for p in self.state.open_promises):
            return
        self.state.open_promises.append(
            Promise(text=text, created_day=self.state.time.day)
        )
        if len(self.state.open_promises) > MAX_OPEN_PROMISES:
            self.state.open_promises = self.state.open_promises[-MAX_OPEN_PROMISES:]

    def resolve_promise(self, text: str) -> bool:
        """Remove a promise by (fuzzy) text match. Returns True if removed."""
        text = (text or "").strip().lower()
        if not text:
            return False
        for i, p in enumerate(self.state.open_promises):
            pt = p.text.lower()
            if text == pt or text in pt or pt in text:
                del self.state.open_promises[i]
                return True
        return False

    # --- Story ---

    def complete_story_beat(self, beat_id: str, sets_flag: str) -> None:
        if beat_id not in self.state.story.completed_beats:
            self.state.story.completed_beats.append(beat_id)
        if sets_flag:
            self.state.flags[sets_flag] = True

    # Mastery threshold used for "topics mastered" counts (story triggers)
    TOPIC_MASTERED_THRESHOLD = 0.6
    # Vocab milestones Aoi acknowledges once each
    VOCAB_MILESTONES = (50, 100, 200)

    def learning_stats(self) -> dict:
        """Compact learning stats for story triggers and the recap screen."""
        topics_mastered = sum(
            1 for t in self.state.learning.topics.values()
            if t.mastery >= self.TOPIC_MASTERED_THRESHOLD
        )
        return {
            "vocab_count": len(self.state.learning.vocab),
            "topics_mastered": topics_mastered,
            "level": self.state.learning.overall_level,
        }

    def pending_milestone_note(self, player_name: str = "Spieler") -> str | None:
        """One-time director notes for progress milestones.

        Returns a short German note for the system prompt when a level-up
        or vocab milestone hasn't been acknowledged yet, and marks it as
        celebrated (via flags) so it fires only once.
        """
        flags = self.state.flags
        level = self.state.learning.overall_level
        if level != "N5" and not flags.get(f"milestone_level_{level}"):
            flags[f"milestone_level_{level}"] = True
            return (
                f"MEILENSTEIN: {player_name} hat gerade Niveau {level} erreicht. "
                f"Lass Aoi das beiläufig, aber aufrichtig würdigen "
                f"(z.B. Rückblick auf die Anfänge) — kein großes Zeremoniell."
            )
        vocab_count = len(self.state.learning.vocab)
        for m in self.VOCAB_MILESTONES:
            if vocab_count >= m and not flags.get(f"milestone_vocab_{m}"):
                flags[f"milestone_vocab_{m}"] = True
                return (
                    f"MEILENSTEIN: {player_name} kennt inzwischen über {m} Vokabeln "
                    f"aus euren Gesprächen. Lass Aoi den Fortschritt einmal "
                    f"beiläufig würdigen."
                )
        return None

    def _update_weak_points(self) -> None:
        """Recalculate the top-5 weakest topics."""
        if not self.state.learning.topics:
            self.state.learning.weak_points = []
            return
        sorted_topics = sorted(
            self.state.learning.topics.values(),
            key=lambda t: t.mastery,
        )
        self.state.learning.weak_points = [
            t.topic for t in sorted_topics[:5]
        ]

    def get_context_summary(self, player_name: str = "Spieler") -> str:
        s = self.state
        lines = [
            f"Spieler: {player_name}",
            f"Tag: {s.time.day}",
            f"Uhrzeit: {s.time.hour}:00 ({s.time.period})",
            f"Ort: {s.current_location}",
            f"Hintergrund: {s.current_background}",
            f"Aoi-Zuneigung: {s.affection.tone} (Score: {s.affection.weighted_score:.0f})",
        ]
        if s.learning.weak_points:
            lines.append(f"Schwächen: {', '.join(s.learning.weak_points)}")
        lines.append(f"JLPT-Schätzung: {s.learning.overall_level}")
        lines.append(f"Interaktionen: {s.learning.total_interactions}")
        if s.open_promises:
            promises = "; ".join(
                f"{p.text} (Tag {p.created_day})" for p in s.open_promises
            )
            lines.append(f"Offene Versprechen/Verabredungen: {promises}")
        return "\n".join(lines)

    def get_state_dict(self) -> dict:
        return self.state.model_dump()

    # --- Save Slot Management ---

    def _saves_dir(self) -> Path:
        d = self.data_dir / self.SAVES_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _slot_path(self, slot_id: int) -> Path:
        return self._saves_dir() / f"slot_{slot_id}.json"

    def save_to_slot(self, slot_id: int, name: str = "") -> SaveSlotMeta:
        """Save current game state to a numbered slot."""
        if not 1 <= slot_id <= self.MAX_SAVE_SLOTS:
            raise ValueError(f"Slot ID must be between 1 and {self.MAX_SAVE_SLOTS}")

        now = datetime.now(timezone.utc).isoformat()
        auto_name = name or f"Tag {self.state.time.day} - {self.state.current_background}"

        meta = SaveSlotMeta(
            slot_id=slot_id,
            name=auto_name,
            day_number=self.state.time.day,
            current_character=self.state.current_character,
            current_background=self.state.current_background,
            saved_at=now,
            turn_count=len(self.state.conversation_history),
        )

        slot_data = SaveSlotData(meta=meta, state=self.state.model_copy(deep=True))

        slot_path = self._slot_path(slot_id)
        tmp_path = slot_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                slot_data.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(slot_path)
        except OSError as e:
            logger.error("Failed to save slot %d: %s", slot_id, e)
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        return meta

    def load_from_slot(self, slot_id: int) -> GameState:
        """Load game state from a numbered slot, replacing current state."""
        slot_path = self._slot_path(slot_id)
        if not slot_path.exists():
            raise FileNotFoundError(f"Save slot {slot_id} does not exist")

        raw = slot_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        slot_data = SaveSlotData.model_validate(data)
        self.state = slot_data.state.model_copy(deep=True)
        self.save()
        return self.state

    def list_save_slots(self) -> list[SaveSlotMeta]:
        """List all existing save slots with metadata."""
        slots: list[SaveSlotMeta] = []
        saves_dir = self._saves_dir()
        for i in range(1, self.MAX_SAVE_SLOTS + 1):
            slot_path = saves_dir / f"slot_{i}.json"
            if slot_path.exists():
                try:
                    raw = slot_path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    slot_data = SaveSlotData.model_validate(data)
                    slots.append(slot_data.meta)
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning("Corrupt save slot %d: %s", i, e)
        return slots

    def delete_save_slot(self, slot_id: int) -> bool:
        """Delete a save slot. Returns True if deleted, False if not found."""
        slot_path = self._slot_path(slot_id)
        if slot_path.exists():
            slot_path.unlink()
            return True
        return False
