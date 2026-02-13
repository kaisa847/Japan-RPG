"""Parse Claude's XML scene responses into structured data."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Regex: detect reversed furigana like ひらがな[漢字] and fix to 漢字[ひらがな]
_HIRAGANA_CHAR = r'[\u3040-\u309F]'
_KANJI_CHAR = r'[\u3005-\u3007\u3400-\u4DBF\u4E00-\u9FFF\u30F5\u30F6]'

# Any bracket-annotation pattern: (some chars)[some chars]
_ANY_BRACKET_RE = re.compile(
    r'([^\[\]]+)\[([^\[\]]+)\]'
)


def _is_hiragana(s: str) -> bool:
    return bool(s) and all('\u3040' <= c <= '\u309F' for c in s)


def _is_kanji(s: str) -> bool:
    return bool(s) and all(
        '\u4E00' <= c <= '\u9FFF' or '\u3400' <= c <= '\u4DBF'
        or '\u3005' <= c <= '\u3007'
        or c in ('\u30F5', '\u30F6')
        for c in s
    )


def _has_kanji(s: str) -> bool:
    """Check if a string contains at least one kanji character."""
    return any(
        '\u4E00' <= c <= '\u9FFF' or '\u3400' <= c <= '\u4DBF'
        or '\u3005' <= c <= '\u3007'
        or c in ('\u30F5', '\u30F6')
        for c in s
    )


def _fix_reversed_furigana(text: str) -> str:
    """Fix reversed furigana notation: ひらがな[漢字] → 漢字[ひらがな].

    Scans for all X[Y] patterns:
    - Correct (leave as-is): kanji+kana mix with kanji[hiragana], e.g. お願い[おねがい]
    - Reversed (fix): hiragana[kanji], e.g. のど[喉] → 喉[のど]
    """
    if not text:
        return text

    def _fix_match(m: re.Match) -> str:
        before = m.group(1)
        inside = m.group(2)

        # Correct: before contains kanji and inside is hiragana reading
        # Covers pure kanji 漢字[かんじ] and mixed お願い[おねがい]
        if _has_kanji(before) and _is_hiragana(inside):
            return m.group(0)

        # Reversed: ...hiragana[kanji] — extract trailing hiragana from 'before'
        if _is_kanji(inside):
            # Find how many trailing chars in 'before' are hiragana
            trailing_kana = []
            for c in reversed(before):
                if '\u3040' <= c <= '\u309F':
                    trailing_kana.append(c)
                else:
                    break
            if trailing_kana:
                kana = ''.join(reversed(trailing_kana))
                prefix = before[:-len(kana)]
                return f"{prefix}{inside}[{kana}]"

        # Unknown pattern, leave as-is
        return m.group(0)

    return _ANY_BRACKET_RE.sub(_fix_match, text)


# Aoi-only valid expressions
CHARACTER_EXPRESSIONS: dict[str, list[str]] = {
    "aoi": [
        "neutral", "happy", "excited", "curious", "talking",
        "laughing", "surprised", "thinking", "embarrassed",
        "determined", "worried", "sleepy",
    ],
}

ALL_EXPRESSIONS = set()
for exprs in CHARACTER_EXPRESSIONS.values():
    ALL_EXPRESSIONS.update(exprs)


# --- Data Models ---


class AnalysisData(BaseModel):
    grammar_topic: Optional[str] = None
    mastery_delta: float = 0.0
    error_correction: Optional[str] = None
    affection_deltas: dict[str, float] = {}


class SceneStatus(BaseModel):
    time_update: Optional[str] = None
    scene_end: bool = False
    suggested_next: list[str] = []


class SceneData(BaseModel):
    character: Optional[str] = None
    expression: str = "neutral"
    background: Optional[str] = None
    dialog_jp: str = ""
    dialog_jp_furigana: str = ""
    dialog_de: str = ""
    raw_response: str = ""
    parse_errors: list[str] = []
    analysis: Optional[AnalysisData] = None
    scene_status: Optional[SceneStatus] = None


class ResponseParser:

    @staticmethod
    def parse_scene(raw_response: str) -> SceneData:
        if not raw_response or not raw_response.strip():
            return SceneData(
                raw_response=raw_response or "",
                parse_errors=["Empty response from Claude"],
            )

        scene_xml = ResponseParser._extract_xml_block(raw_response, "scene")
        if not scene_xml:
            return SceneData(
                dialog_jp=raw_response.strip(),
                raw_response=raw_response,
                parse_errors=["No <scene> tag found in response"],
            )

        data = ResponseParser._parse_xml(scene_xml)
        if not data:
            data = ResponseParser._parse_regex_fallback(scene_xml)

        errors: list[str] = []

        character = ResponseParser._sanitize_character_id(data.get("character", ""))
        if not character:
            character = None

        expression = data.get("expression", "neutral").strip().lower()
        expression = ResponseParser._validate_expression(expression, character, errors)

        background = data.get("background", "").strip() or None

        dialog_jp = html.unescape(data.get("dialog_jp", "").strip())
        dialog_jp_furigana = html.unescape(data.get("dialog_jp_furigana", "").strip())
        dialog_de = html.unescape(data.get("dialog_de", "").strip())

        # Normalize fullwidth brackets ［ ］ to halfwidth [ ]
        if dialog_jp_furigana:
            dialog_jp_furigana = dialog_jp_furigana.replace('\uff3b', '[').replace('\uff3d', ']')

        # Fix reversed furigana notation (e.g. のど[喉] → 喉[のど])
        if dialog_jp_furigana:
            fixed = _fix_reversed_furigana(dialog_jp_furigana)
            if fixed != dialog_jp_furigana:
                errors.append("Fixed reversed furigana notation")
                dialog_jp_furigana = fixed

        # Fallback: if furigana is missing, use plain dialog_jp
        if dialog_jp and not dialog_jp_furigana:
            dialog_jp_furigana = dialog_jp
            errors.append("Missing dialog_jp_furigana, falling back to dialog_jp")

        # Parse optional analysis block
        analysis = ResponseParser._parse_analysis(raw_response)

        # Parse optional scene_status block
        scene_status = ResponseParser._parse_scene_status(raw_response)

        return SceneData(
            character=character,
            expression=expression,
            background=background,
            dialog_jp=dialog_jp,
            dialog_jp_furigana=dialog_jp_furigana,
            dialog_de=dialog_de,
            raw_response=raw_response,
            parse_errors=errors,
            analysis=analysis,
            scene_status=scene_status,
        )

    # --- XML Extraction ---

    @staticmethod
    def _extract_xml_block(text: str, tag: str) -> Optional[str]:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def _parse_xml(scene_xml: str) -> Optional[dict]:
        try:
            root = ET.fromstring(scene_xml)
            result = {}
            for tag in ("character", "expression", "background",
                        "dialog_jp", "dialog_jp_furigana", "dialog_de"):
                elem = root.find(tag)
                if elem is not None and elem.text:
                    result[tag] = elem.text
            return result
        except ET.ParseError:
            return None

    @staticmethod
    def _parse_regex_fallback(scene_xml: str) -> dict:
        result = {}
        for tag in ("character", "expression", "background",
                     "dialog_jp", "dialog_jp_furigana", "dialog_de"):
            match = re.search(rf"<{tag}>(.*?)</{tag}>", scene_xml, re.DOTALL)
            if match:
                result[tag] = match.group(1)
        return result

    # --- Analysis Parsing ---

    @staticmethod
    def _parse_analysis(raw_response: str) -> Optional[AnalysisData]:
        analysis_xml = ResponseParser._extract_xml_block(raw_response, "analysis")
        if not analysis_xml:
            return None

        data = ResponseParser._parse_xml_tags(analysis_xml, [
            "grammar_topic", "mastery_delta", "error_correction",
            "affection_language_effort", "affection_cultural_interest",
            "affection_personal_bond", "affection_humor", "affection_reliability",
        ])

        affection_deltas = {}
        affection_keys = {
            "affection_language_effort": "language_effort",
            "affection_cultural_interest": "cultural_interest",
            "affection_personal_bond": "personal_bond",
            "affection_humor": "humor",
            "affection_reliability": "reliability",
        }
        for xml_key, field_name in affection_keys.items():
            val = data.get(xml_key, "0")
            try:
                num = float(val)
                if num != 0:
                    affection_deltas[field_name] = num
            except (ValueError, TypeError):
                pass

        mastery_delta = 0.0
        try:
            mastery_delta = float(data.get("mastery_delta", "0"))
        except (ValueError, TypeError):
            pass

        return AnalysisData(
            grammar_topic=data.get("grammar_topic") or None,
            mastery_delta=mastery_delta,
            error_correction=data.get("error_correction") or None,
            affection_deltas=affection_deltas,
        )

    # --- Scene Status Parsing ---

    @staticmethod
    def _parse_scene_status(raw_response: str) -> Optional[SceneStatus]:
        status_xml = ResponseParser._extract_xml_block(raw_response, "scene_status")
        if not status_xml:
            return None

        data = ResponseParser._parse_xml_tags(status_xml, [
            "time_update", "scene_end", "suggested_next",
        ])

        time_update = data.get("time_update") or None
        scene_end = data.get("scene_end", "").strip().lower() == "true"

        suggested_next: list[str] = []
        raw_next = data.get("suggested_next", "").strip()
        if raw_next:
            suggested_next = [s.strip() for s in raw_next.split("|") if s.strip()]

        return SceneStatus(
            time_update=time_update,
            scene_end=scene_end,
            suggested_next=suggested_next,
        )

    # --- Helper ---

    @staticmethod
    def _parse_xml_tags(xml_str: str, tags: list[str]) -> dict:
        """Parse specific tags from an XML string using regex (forgiving)."""
        result = {}
        for tag in tags:
            match = re.search(rf"<{tag}>(.*?)</{tag}>", xml_str, re.DOTALL)
            if match:
                result[tag] = match.group(1).strip()
        return result

    @staticmethod
    def _validate_expression(
        expression: str,
        character: Optional[str],
        errors: list[str],
    ) -> str:
        if character and character in CHARACTER_EXPRESSIONS:
            valid = CHARACTER_EXPRESSIONS[character]
            if expression in valid:
                return expression
            errors.append(
                f"Invalid expression '{expression}' for character '{character}', "
                f"falling back to 'neutral'"
            )
            return "neutral"

        # Unknown character or no character: accept if it's any known expression
        if expression in ALL_EXPRESSIONS:
            return expression

        errors.append(f"Unknown expression '{expression}', falling back to 'neutral'")
        return "neutral"

    @staticmethod
    def _sanitize_character_id(char_id: str) -> str:
        char_id = char_id.strip().lower().replace(" ", "_").replace("-", "_")
        return char_id
