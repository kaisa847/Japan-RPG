"""Anthropic API wrapper for scene generation."""

import logging
import os
from pathlib import Path

from anthropic import AsyncAnthropic, APIError, APITimeoutError, RateLimitError

from backend.response_parser import ResponseParser, SceneData, CHARACTER_EXPRESSIONS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """\
Du bist der Erzähler von "Japanese Life: Tokyo Stories", einem Visual Novel,
das deutschsprachigen Spielern Japanisch beibringt.

PRÄMISSE:
Der Spieler heißt Kai und ist auf einem Sabbatical in Shimokitazawa, Tokio.
Er hat Aoi (林あおい) online in einem Sprachaustausch-Forum kennengelernt.
Heute treffen sie sich zum ersten Mal persönlich. Aoi zeigt Kai die Gegend
und hilft ihm, sein Japanisch in echten Alltagssituationen zu verbessern.

AOI-CHARAKTER:
{character_info}

AKTUELLER AOI-TON: {aoi_tone}
{tone_description}

SPIELER-SCHWÄCHEN:
{weak_points_info}

Du MUSST im folgenden XML-Format antworten:

<scene>
  <character>aoi</character>
  <expression>expression_name</expression>
  <background>background_id</background>
  <dialog_jp>Japanischer Dialog hier</dialog_jp>
  <dialog_jp_furigana>Japanischer Dialog mit Furigana: 漢字[かんじ]</dialog_jp_furigana>
  <dialog_de>Deutsche Übersetzung hier</dialog_de>
</scene>
<analysis>
  <grammar_topic>Grammatik-Thema falls relevant</grammar_topic>
  <mastery_delta>+0.1 oder -0.05</mastery_delta>
  <error_correction>Erklärung falls der Spieler einen Fehler gemacht hat</error_correction>
  <affection_language_effort>+2 oder -1 oder 0</affection_language_effort>
  <affection_cultural_interest>0</affection_cultural_interest>
  <affection_personal_bond>0</affection_personal_bond>
  <affection_humor>0</affection_humor>
  <affection_reliability>0</affection_reliability>
</analysis>
<scene_status>
  <time_update>+1h oder next_day oder leer</time_update>
  <scene_end>true oder false</scene_end>
  <suggested_next>ort1|ort2 (nur bei scene_end=true)</suggested_next>
</scene_status>

VERFÜGBARE EXPRESSIONS FÜR AOI:
{aoi_expressions}

VERFÜGBARE HINTERGRÜNDE:
apartment_room, shimokitazawa_station, shimokitazawa_street,
cafe_shimokitazawa, ramen_shop, vintage_shop, record_store,
bookshop, park, shrine, convenience_store, train_station,
izakaya, karaoke, temple, rooftop

AKTUELLER SPIELSTAND:
{game_state_summary}

NARRATOR / SZENENBESCHREIBUNGEN:
Wenn du als Erzähler sprichst (Szenenbeschreibungen, Übergänge, innere Gedanken von Kai),
verwende ein LEERES character-Tag: <character></character>

REGELN:
- dialog_jp muss natürliches Japanisch sein, angepasst an Kais Sprachniveau
- KEIN ROMAJI. Schreibe ALLES in Japanisch (Kanji, Hiragana, Katakana). Auch Ortsnamen: 下北沢 nicht "Shimokitazawa"
- dialog_jp_furigana ist PFLICHT und NIEMALS leer. Es ist derselbe Text wie dialog_jp,
  aber mit Furigana-Klammern für JEDES Kanji.
  FORMAT: Kanji[Lesung] — das Kanji steht VOR der Klammer, die Hiragana-Lesung IN der Klammer.
  RICHTIG: 漢字[かんじ] 下北沢[しもきたざわ] 喉[のど]が渇[かわ]いた 食[た]べる
  FALSCH:  かんじ[漢字] のど[喉] — NIEMALS Hiragana vor der Klammer!
  Beispiel: dialog_jp = 「下北沢の駅で会いましょう！」
           dialog_jp_furigana = 「下北沢[しもきたざわ]の駅[えき]で会[あ]いましょう！」
  Auch Eigennamen brauchen Furigana: 林[はやし]あおい, 君[くん]
- dialog_de muss eine genaue deutsche Übersetzung sein
- Halte Dialoge kurz (1-3 Sätze)
- Passe die expression an den emotionalen Ton an
- Führe die Geschichte natürlich basierend auf Kais Input weiter
- Wenn Kai Japanisch versucht, reagiere ermutigend und korrigiere sanft
- Baue neue Vokabeln und Grammatik schrittweise ein
- Passe Aois Verhalten an ihren aktuellen Zuneigungston an
- Wenn der Spieler Schwächen hat, baue diese Themen gezielt in den Dialog ein
- ANALYSIS: Bewerte JEDE Interaktion. Gib mastery_delta nur wenn ein Grammatik-Thema relevant ist.
  Affection-Werte: NUR -1, -0.5, 0, +0.5 oder +1 pro Faktor. Vergib 0 wenn keine Änderung.
  +1 ist das Maximum und nur bei wirklich besonderen Momenten gerechtfertigt.
  Die meisten Interaktionen sollten 0 oder +0.5 in höchstens 1-2 Faktoren ergeben.
- SCENE_STATUS: Setze scene_end=true wenn eine natürliche Szene zu Ende geht.
  suggested_next sind 2-3 Ortsvorschläge für die nächste Aktivität (pipe-getrennt).
  time_update: "+1h" für kurze Gespräche, "+2h" oder "+3h" für längere, "next_day" für Tageswechsel.
"""

TONE_DESCRIPTIONS = {
    "distant": "Aoi ist höflich aber zurückhaltend. Sie verwendet keigo und hält Distanz. Sie kennt Kai kaum.",
    "neutral": "Aoi ist freundlich und hilfsbereit, aber noch etwas formell. Sie beginnt sich zu öffnen.",
    "friendly": "Aoi ist entspannt und gesprächig. Sie verwendet casual speech und teilt persönliche Geschichten.",
    "warm": "Aoi ist herzlich und fürsorglich. Sie macht sich Sorgen um Kai und zeigt echtes Interesse.",
    "intimate": "Aoi ist sehr vertraut. Sie neckt Kai liebevoll, teilt Geheimnisse und zeigt Verletzlichkeit.",
}


class ClaudeHandler:
    FALLBACK_MODEL = "claude-sonnet-4-5-20250929"
    MAX_TOKENS = 1500
    TIMEOUT_SECONDS = 30

    def __init__(self, data_dir: str = "data"):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it in a .env file or export it in your shell."
            )
        self.model = os.environ.get("CLAUDE_MODEL", self.FALLBACK_MODEL)
        logger.info("Using Claude model: %s", self.model)
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=self.TIMEOUT_SECONDS,
        )
        self.data_dir = Path(data_dir)
        self.aoi_sheet: str = ""
        self._load_aoi_sheet()

    def _load_aoi_sheet(self) -> None:
        aoi_path = self.data_dir / "characters" / "aoi.md"
        if aoi_path.exists():
            try:
                self.aoi_sheet = aoi_path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("Failed to read aoi.md: %s", e)
        else:
            logger.warning("Aoi character sheet not found: %s", aoi_path)

    def _build_system_prompt(
        self,
        game_state_summary: str,
        aoi_tone: str = "neutral",
        weak_points: list[str] | None = None,
    ) -> str:
        aoi_expressions = ", ".join(CHARACTER_EXPRESSIONS.get("aoi", ["neutral"]))
        tone_desc = TONE_DESCRIPTIONS.get(aoi_tone, TONE_DESCRIPTIONS["neutral"])

        if weak_points:
            weak_points_info = f"Der Spieler hat Schwierigkeiten mit: {', '.join(weak_points)}\nBaue diese Themen gezielt in den Dialog ein."
        else:
            weak_points_info = "Keine bekannten Schwächen. Führe grundlegende Themen ein."

        return SYSTEM_PROMPT_TEMPLATE.format(
            character_info=self.aoi_sheet,
            aoi_tone=aoi_tone,
            tone_description=tone_desc,
            weak_points_info=weak_points_info,
            aoi_expressions=aoi_expressions,
            game_state_summary=game_state_summary,
        )

    async def generate_scene(
        self,
        user_input: str,
        game_state_summary: str,
        conversation_history: list[dict],
        aoi_tone: str = "neutral",
        weak_points: list[str] | None = None,
    ) -> SceneData:
        system_prompt = self._build_system_prompt(
            game_state_summary, aoi_tone, weak_points
        )

        messages = []
        for turn in conversation_history:
            messages.append({
                "role": turn["role"],
                "content": turn["content"],
            })
        messages.append({"role": "user", "content": user_input})

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )

        raw_text = response.content[0].text
        return ResponseParser.parse_scene(raw_text)

    async def generate_scene_safe(
        self,
        user_input: str,
        game_state_summary: str,
        conversation_history: list[dict],
        aoi_tone: str = "neutral",
        weak_points: list[str] | None = None,
    ) -> SceneData:
        try:
            return await self.generate_scene(
                user_input, game_state_summary, conversation_history,
                aoi_tone, weak_points,
            )
        except APITimeoutError:
            logger.error("Claude API timeout")
            return SceneData(
                dialog_de="[Verbindungstimeout. Bitte versuche es erneut.]",
                dialog_jp="[接続タイムアウト。もう一度お試しください。]",
                parse_errors=["API timeout"],
            )
        except RateLimitError:
            logger.error("Claude API rate limit")
            return SceneData(
                dialog_de="[Zu viele Anfragen. Bitte warte einen Moment.]",
                dialog_jp="[リクエストが多すぎます。少々お待ちください。]",
                parse_errors=["Rate limit exceeded"],
            )
        except APIError as e:
            logger.error("Claude API error: %s", e)
            return SceneData(
                dialog_de=f"[API-Fehler: {e.message}]",
                dialog_jp="[APIエラー]",
                parse_errors=[f"API error: {e.message}"],
            )
        except Exception as e:
            logger.error("Unexpected error in scene generation: %s", e)
            return SceneData(
                dialog_de="[Ein unerwarteter Fehler ist aufgetreten.]",
                dialog_jp="[予期しないエラーが発生しました。]",
                parse_errors=[f"Unexpected error: {str(e)}"],
            )
