"""LLM-powered scene generation for the Visual Novel Engine."""

import json
import logging
import os
from pathlib import Path

from backend.llm_providers import LLMProvider, AnthropicProvider, create_provider
from backend.response_parser import ResponseParser, SceneData, CHARACTER_EXPRESSIONS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """\
Du bist der Erzähler von "Japanese Life: Tokyo Stories", einem Visual Novel,
das deutschsprachigen Spielern Japanisch beibringt.

PRÄMISSE:
Der Spieler heißt {player_name} und ist auf einem Sabbatical in Shimokitazawa, Tokio.
Er hat Aoi (林あおい) online in einem Sprachaustausch-Forum kennengelernt.
Heute treffen sie sich zum ersten Mal persönlich. Aoi zeigt {player_name} die Gegend
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
{available_backgrounds}

AKTUELLER SPIELSTAND:
{game_state_summary}

NARRATOR / SZENENBESCHREIBUNGEN:
Wenn du als Erzähler sprichst (Szenenbeschreibungen, Übergänge, innere Gedanken von {player_name}),
verwende ein LEERES character-Tag: <character></character>

REGELN:
- dialog_jp muss natürliches Japanisch sein, angepasst an das Sprachniveau von {player_name}
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
- Führe die Geschichte natürlich basierend auf dem Input von {player_name} weiter
- Wenn {player_name} Japanisch versucht, reagiere ermutigend und korrigiere sanft
- Baue neue Vokabeln und Grammatik schrittweise ein
- Passe Aois Verhalten an ihren aktuellen Zuneigungston an
- Wenn der Spieler Schwächen hat, baue diese Themen gezielt in den Dialog ein
- ANALYSIS: Bewerte JEDE Interaktion. Gib mastery_delta nur wenn ein Grammatik-Thema relevant ist.
  Affection-Werte: NUR -1, -0.5, 0, +0.5 oder +1 pro Faktor. Vergib 0 wenn keine Änderung.
  +1 ist das Maximum und nur bei wirklich besonderen Momenten gerechtfertigt.
  Die meisten Interaktionen sollten 0 oder +0.5 in höchstens 1-2 Faktoren ergeben.
- SCENE_STATUS: Setze scene_end=true wenn eine natürliche Szene zu Ende geht.
  suggested_next sind 2-3 Ortsvorschläge für die nächste Aktivität (pipe-getrennt).
  time_update ist PFLICHT und darf NIEMALS leer sein. Die Spielzeit MUSS voranschreiten:
  * Bei scene_end=true: IMMER "+1h", "+2h" oder "+3h" setzen (je nach Länge der vergangenen Aktivität).
    Ein Cafébesuch dauert ca. 1-2h, ein Einkaufsbummel 2-3h, ein Abendessen 2h, etc.
  * Während einer laufenden Szene: "+1h" nach ca. 4-6 Gesprächsrunden setzen, damit die Zeit realistisch vergeht.
  * "next_day" nur für Tageswechsel (z.B. "Lass uns morgen weitermachen").
  * NIEMALS leer lassen! Wenn du unsicher bist, setze mindestens "+1h".
"""

TONE_DESCRIPTIONS = {
    "distant": "Aoi ist höflich aber zurückhaltend. Sie verwendet keigo und hält Distanz. Sie kennt {player_name} kaum.",
    "neutral": "Aoi ist freundlich und hilfsbereit, aber noch etwas formell. Sie beginnt sich zu öffnen.",
    "friendly": "Aoi ist entspannt und gesprächig. Sie verwendet casual speech und teilt persönliche Geschichten.",
    "warm": "Aoi ist herzlich und fürsorglich. Sie macht sich Sorgen um {player_name} und zeigt echtes Interesse.",
    "intimate": "Aoi ist sehr vertraut. Sie neckt {player_name} liebevoll, teilt Geheimnisse und zeigt Verletzlichkeit.",
}


class ClaudeHandler:
    FALLBACK_MODEL = "claude-sonnet-4-5-20250929"
    MAX_TOKENS = 1500
    TIMEOUT_SECONDS = 30

    def __init__(self, data_dir: str = "data"):
        # Build default provider from environment (global API key)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.default_provider: LLMProvider | None = None

        if api_key:
            model = os.environ.get("CLAUDE_MODEL", self.FALLBACK_MODEL)
            logger.info("Using default Claude model: %s", model)
            self.default_provider = AnthropicProvider(
                api_key=api_key, model=model, timeout=self.TIMEOUT_SECONDS
            )
        else:
            logger.warning(
                "ANTHROPIC_API_KEY not set. Global provider unavailable. "
                "Users must configure their own API key."
            )

        self.data_dir = Path(data_dir)
        self.aoi_sheet: str = ""
        self._load_aoi_sheet()
        self.locations: dict = {}
        self._load_locations()

    def _load_locations(self) -> None:
        loc_path = self.data_dir / "locations.json"
        if loc_path.exists():
            try:
                self.locations = json.loads(loc_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Failed to read locations.json: %s", e)
        else:
            logger.warning("Locations config not found: %s", loc_path)

    def get_background_ids(self) -> list[str]:
        """Return sorted list of location IDs from config."""
        return sorted(self.locations.get("locations", {}).keys())

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
        player_name: str = "Spieler",
    ) -> str:
        aoi_expressions = ", ".join(CHARACTER_EXPRESSIONS.get("aoi", ["neutral"]))
        tone_desc = TONE_DESCRIPTIONS.get(aoi_tone, TONE_DESCRIPTIONS["neutral"])
        tone_desc = tone_desc.format(player_name=player_name)

        if weak_points:
            weak_points_info = f"Der Spieler hat Schwierigkeiten mit: {', '.join(weak_points)}\nBaue diese Themen gezielt in den Dialog ein."
        else:
            weak_points_info = "Keine bekannten Schwächen. Führe grundlegende Themen ein."

        backgrounds = ", ".join(self.get_background_ids())

        return SYSTEM_PROMPT_TEMPLATE.format(
            character_info=self.aoi_sheet,
            aoi_tone=aoi_tone,
            tone_description=tone_desc,
            weak_points_info=weak_points_info,
            aoi_expressions=aoi_expressions,
            available_backgrounds=backgrounds,
            game_state_summary=game_state_summary,
            player_name=player_name,
        )

    async def generate_scene(
        self,
        user_input: str,
        game_state_summary: str,
        conversation_history: list[dict],
        aoi_tone: str = "neutral",
        weak_points: list[str] | None = None,
        player_name: str = "Spieler",
        provider: LLMProvider | None = None,
    ) -> SceneData:
        effective_provider = provider or self.default_provider
        if not effective_provider:
            return SceneData(
                dialog_de="[Kein API-Schlüssel konfiguriert. Bitte eigenen Key in den Einstellungen hinterlegen.]",
                dialog_jp="[APIキーが設定されていません。設定で自分のキーを入力してください。]",
                parse_errors=["No LLM provider available"],
            )

        system_prompt = self._build_system_prompt(
            game_state_summary, aoi_tone, weak_points, player_name=player_name
        )

        messages = []
        for turn in conversation_history:
            messages.append({
                "role": turn["role"],
                "content": turn["content"],
            })
        messages.append({"role": "user", "content": user_input})

        raw_text = await effective_provider.generate(
            system_prompt, messages, self.MAX_TOKENS
        )
        return ResponseParser.parse_scene(raw_text)

    async def generate_scene_safe(
        self,
        user_input: str,
        game_state_summary: str,
        conversation_history: list[dict],
        aoi_tone: str = "neutral",
        weak_points: list[str] | None = None,
        player_name: str = "Spieler",
        provider: LLMProvider | None = None,
    ) -> SceneData:
        try:
            return await self.generate_scene(
                user_input, game_state_summary, conversation_history,
                aoi_tone, weak_points, player_name=player_name,
                provider=provider,
            )
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            # Check for common error patterns across providers
            lower_msg = error_msg.lower()
            if "timeout" in lower_msg or "timed out" in lower_msg:
                logger.error("LLM API timeout: %s", e)
                return SceneData(
                    dialog_de="[Verbindungstimeout. Bitte versuche es erneut.]",
                    dialog_jp="[接続タイムアウト。もう一度お試しください。]",
                    parse_errors=["API timeout"],
                )
            elif "rate" in lower_msg and "limit" in lower_msg:
                logger.error("LLM API rate limit: %s", e)
                return SceneData(
                    dialog_de="[Zu viele Anfragen. Bitte warte einen Moment.]",
                    dialog_jp="[リクエストが多すぎます。少々お待ちください。]",
                    parse_errors=["Rate limit exceeded"],
                )
            elif "invalid" in lower_msg and ("key" in lower_msg or "auth" in lower_msg):
                logger.error("LLM API auth error: %s", e)
                return SceneData(
                    dialog_de="[Ungültiger API-Schlüssel. Bitte überprüfe deine Einstellungen.]",
                    dialog_jp="[無効なAPIキー。設定を確認してください。]",
                    parse_errors=[f"Authentication error: {error_msg}"],
                )
            else:
                logger.error("LLM error (%s): %s", error_type, e)
                return SceneData(
                    dialog_de=f"[API-Fehler: {error_msg}]",
                    dialog_jp="[APIエラー]",
                    parse_errors=[f"{error_type}: {error_msg}"],
                )
