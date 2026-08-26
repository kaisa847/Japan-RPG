"""Canonical grammar topic taxonomy and JLPT level estimation.

The topic names are the ONLY values Claude is allowed to use for
<grammar_topic>. Keeping them canonical prevents the mastery tracking
from fragmenting into near-duplicate free-form strings.
"""

from __future__ import annotations

import re
import unicodedata

# Compact canonical topic lists. German labels, kept short so the full
# list stays cheap when injected into the system prompt.
N5_TOPICS: list[str] = [
    "です/ます-Form",
    "Partikel は",
    "Partikel が",
    "Partikel を",
    "Partikel に",
    "Partikel で",
    "Partikel へ",
    "Partikel の",
    "Partikel も",
    "Partikel と",
    "Partikel から/まで",
    "Partikel か (Frage)",
    "Partikel ね/よ",
    "Demonstrativa これ/それ/あれ",
    "Existenz ある/いる",
    "Verben Präsens/Futur",
    "Verben Vergangenheit",
    "Verben Verneinung",
    "て-Form",
    "て-Form Verlaufsform (ている)",
    "て-Form Bitte (てください)",
    "Adjektive い",
    "Adjektive な",
    "Adjektive Vergangenheit",
    "Nomen + です",
    "Zahlen und Zählwörter",
    "Uhrzeit und Datum",
    "Wollen (たい-Form)",
    "Einladung (ませんか/ましょう)",
    "Können (Potenzialform Basis)",
    "Erlaubnis (てもいい)",
    "Verbot (てはいけない)",
    "Komparativ (より/のほうが)",
    "Grund (から)",
    "Vermutung (でしょう)",
    "Fragewörter",
    "Ortsangaben (上/下/中/前 …)",
    "Häufigkeitsadverbien",
]

N4_TOPICS: list[str] = [
    "Casual Speech (だ-Form)",
    "た-Form Erfahrung (たことがある)",
    "Aufzählung (たり…たり)",
    "Konditional と",
    "Konditional ば",
    "Konditional たら",
    "Konditional なら",
    "Absicht (つもり/予定)",
    "Vorhaben (ようと思う)",
    "Potenzialform",
    "Passiv",
    "Kausativ",
    "Imperativ",
    "Geben/Bekommen (あげる/くれる/もらう)",
    "Müssen (なければならない)",
    "Ratschlag (たほうがいい)",
    "Verlaufsresultat (てある/ておく)",
    "Ausprobieren (てみる)",
    "Werden (ようになる/くなる)",
    "Indirekte Rede (と言う/と思う)",
    "Nominalisierung (の/こと)",
    "Relativsätze",
    "Während (ながら)",
    "Zweck (ために/のに)",
    "Vergleich (そうだ/ようだ/みたい)",
    "Höflichkeit Keigo Basis",
    "Übergabe von Vorschlägen (ましょうか)",
    "Wenn-dann Zeitfolge (とき)",
]

_ALL_TOPICS: list[str] = N5_TOPICS + N4_TOPICS

# Aliases for common free-form variants Claude might still produce.
_ALIASES: dict[str, str] = {
    "te-form": "て-Form",
    "teform": "て-Form",
    "te form": "て-Form",
    "masu-form": "です/ます-Form",
    "desu/masu": "です/ます-Form",
    "desu-masu": "です/ます-Form",
    "hoeflichkeitsform": "です/ます-Form",
    "höflichkeitsform": "です/ます-Form",
    "tai-form": "Wollen (たい-Form)",
    "casual speech": "Casual Speech (だ-Form)",
    "da-form": "Casual Speech (だ-Form)",
    "partikel wa": "Partikel は",
    "partikel ga": "Partikel が",
    "partikel wo": "Partikel を",
    "partikel o": "Partikel を",
    "partikel ni": "Partikel に",
    "partikel de": "Partikel で",
    "partikel no": "Partikel の",
    "partikel mo": "Partikel も",
    "partikel to": "Partikel と",
    "zaehlwoerter": "Zahlen und Zählwörter",
    "zählwörter": "Zahlen und Zählwörter",
    "keigo": "Höflichkeit Keigo Basis",
}


def _norm_key(s: str) -> str:
    """Normalize a topic string for fuzzy comparison."""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = re.sub(r"[\s　]+", " ", s)
    return s


_CANONICAL_BY_KEY: dict[str, str] = {_norm_key(t): t for t in _ALL_TOPICS}


def normalize_topic(raw: str | None) -> str | None:
    """Map a (possibly free-form) topic name onto the canonical taxonomy.

    Returns the canonical topic, or None if no confident match exists.
    Unmatched topics are dropped rather than stored, so the mastery map
    only ever contains canonical entries.
    """
    if not raw or not raw.strip():
        return None
    key = _norm_key(raw)

    if key in _CANONICAL_BY_KEY:
        return _CANONICAL_BY_KEY[key]
    if key in _ALIASES:
        return _ALIASES[key]

    # Substring match: canonical key contained in raw or vice versa.
    # Longest canonical key first so "て-Form Verlaufsform" prefers
    # "て-Form Verlaufsform (ている)" over plain "て-Form".
    for ckey in sorted(_CANONICAL_BY_KEY, key=len, reverse=True):
        if ckey in key or key in ckey:
            return _CANONICAL_BY_KEY[ckey]
    return None


# --- JLPT estimation ---

MASTERED_THRESHOLD = 0.6
LEVEL_UP_RATIO = 0.6
# Require a minimum number of mastered topics so a lucky first session
# with 3 topics doesn't jump the level.
MIN_MASTERED_N5 = 15
MIN_MASTERED_N4 = 12


def estimate_jlpt(topics: dict) -> str:
    """Estimate the JLPT level from canonical topic mastery.

    ``topics`` maps topic name -> object/dict with a ``mastery`` float.
    """
    def _mastery(entry) -> float:
        if isinstance(entry, dict):
            return float(entry.get("mastery", 0.0))
        return float(getattr(entry, "mastery", 0.0))

    n5_mastered = sum(
        1 for t in N5_TOPICS
        if t in topics and _mastery(topics[t]) >= MASTERED_THRESHOLD
    )
    n4_mastered = sum(
        1 for t in N4_TOPICS
        if t in topics and _mastery(topics[t]) >= MASTERED_THRESHOLD
    )

    n5_done = (
        n5_mastered >= MIN_MASTERED_N5
        and n5_mastered / len(N5_TOPICS) >= LEVEL_UP_RATIO
    )
    n4_done = (
        n4_mastered >= MIN_MASTERED_N4
        and n4_mastered / len(N4_TOPICS) >= LEVEL_UP_RATIO
    )

    if n5_done and n4_done:
        return "N3"
    if n5_done:
        return "N4"
    return "N5"


def taxonomy_for_level(level: str) -> list[str]:
    """Return the topic list to expose in the prompt for a given level.

    N5 learners only see N5 topics (keeps the prompt small and the
    input comprehensible); from N4 on the N4 topics are added.
    """
    if level in ("N4", "N3", "N2", "N1"):
        return N5_TOPICS + N4_TOPICS
    return N5_TOPICS
