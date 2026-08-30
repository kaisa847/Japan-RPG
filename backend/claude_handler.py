"""Anthropic API wrapper for scene generation."""

import json
import logging
import os
import re
from pathlib import Path

from anthropic import AsyncAnthropic, APIError, APITimeoutError, RateLimitError

from backend.grammar_taxonomy import taxonomy_for_level
from backend.response_parser import ResponseParser, SceneData, CHARACTER_EXPRESSIONS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """\
Du bist der Erzähler von "Japanese Life: Tokyo Stories", einem Visual Novel,
das deutschsprachigen Spielern Japanisch beibringt.

PRÄMISSE:
{premise}

AOI-CHARAKTER:
{character_info}

AKTUELLER AOI-TON: {aoi_tone}
{tone_description}

SPIELER-SCHWÄCHEN:
{weak_points_info}

SPRACHNIVEAU ({jlpt_level}):
{level_rules}

{memory_block}{vocab_block}{story_block}Du MUSST im folgenden XML-Format antworten:

<scene>
  <character>aoi</character>
  <speaker>Anzeigename, NUR wenn eine Nebenfigur spricht (z.B. マスター) — sonst weglassen</speaker>
  <expression>expression_name</expression>
  <pose>pose_id (nur aus der Posen-Liste; weglassen wenn keine gelistet)</pose>
  <staging>left/center/right und/oder near (optional, siehe Regeln)</staging>
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
  <memory>Nur bei scene_end=true: 1-2 Sätze auf Deutsch, was in dieser Szene passiert ist</memory>
  <new_vocab>言葉[ことば]=Bedeutung|駅[えき]=Bahnhof (0-3 neue/wiederholte Vokabeln, sonst leer)</new_vocab>
  <story_flag>flag_name (NUR wenn der aktuelle Story-Beat stattgefunden hat, sonst weglassen)</story_flag>
  <promise>Kurzbeschreibung, wenn eine konkrete Verabredung/ein Versprechen entstanden ist</promise>
  <promise_resolved>Text des Versprechens, wenn es eingelöst oder gebrochen wurde</promise_resolved>
</scene_status>

VERFÜGBARE EXPRESSIONS FÜR AOI:
{aoi_expressions}

{pose_block}VERFÜGBARE HINTERGRÜNDE:
{available_backgrounds}

AKTUELLER SPIELSTAND:
{game_state_summary}

NARRATOR / SZENENBESCHREIBUNGEN:
Wenn du als Erzähler sprichst (Szenenbeschreibungen, Übergänge, innere Gedanken von {player_name}),
verwende ein LEERES character-Tag: <character></character>
WICHTIG: Erzählertext darf NUR für Szenenübergänge, Ortswechsel oder innere Gedanken von {player_name} verwendet werden.
Beschreibe NIEMALS Aois körperliche Aktionen im Erzählertext (z.B. "Aoi schaute sich um", "Aoi lächelte").
Aois Emotionen werden AUSSCHLIESSLICH über das <expression>-Tag dargestellt — das ist ein Visual Novel!

NEBENFIGUREN (Ladenbesitzer, Passanten, Aois Familie am Telefon, ...):
Wenn eine Nebenfigur spricht, setze <speaker> auf ihren Anzeigenamen (z.B. マスター, 店員[てんいん]さん)
und schreibe in dialog_jp NUR ihre wörtliche Rede — OHNE Erzähltext.
<character> bleibt dabei aoi (sie steht weiter im Bild) oder leer, wenn Aoi nicht anwesend ist.
FALSCH: <character>aoi</character> + dialog_jp = 「あおい、久しぶり！」マスターが言った。
RICHTIG: <character>aoi</character> + <speaker>マスター</speaker> + dialog_jp = 「あおい、久しぶり！」
NIEMALS "Xが言った" oder Ähnliches in dialog_jp — wer spricht, zeigt der Name über der Textbox.
Nebenfiguren bleiben Randfiguren: kurze Auftritte, das Gespräch gehört Aoi und {player_name}.

GESPRÄCHSFÜHRUNG:
- Die assistant-Nachrichten in der Historie zeigen Aois bisherige Dialoge. Die user-Nachrichten sind {player_name}s Eingaben.
- Lies die bisherigen Nachrichten AUFMERKSAM. Reagiere DIREKT auf das, was {player_name} gerade gesagt oder gefragt hat.
- Wenn du {player_name} eine Frage gestellt hast und er darauf antwortet, nimm seine Antwort auf und führe das Gespräch natürlich weiter. Stelle NICHT dieselbe Frage nochmal.
- Wenn {player_name} dir eine Frage stellt, beantworte sie als Aoi.
- Behalte das aktuelle Gesprächsthema im Blick. Wechsle nicht abrupt das Thema, es sei denn {player_name} tut es.
- Behandle {player_name}s Eingabe NIEMALS als deine eigene Aussage. Was {player_name} sagt, ist SEINE Aussage — du reagierst darauf als Aoi.

REGELN:
- dialog_jp enthält AUSSCHLIESSLICH gesprochenen Text — NUR das, was der Charakter tatsächlich SAGT.
  KEINE Handlungsbeschreibungen, Regieanweisungen oder Erzählertext in dialog_jp!
  FALSCH: 「あおいは周りを見回しながら言った。『下北沢へようこそ！』」
  FALSCH: 「*微笑みながら* 下北沢へようこそ！」
  RICHTIG: 「下北沢へようこそ！」
  Das ist ein Visual Novel — Aktionen und Emotionen werden über das <expression>-Tag gezeigt, nicht im Dialog.
- dialog_jp muss natürliches Japanisch sein, angepasst an das Sprachniveau von {player_name}
- KEIN ROMAJI IN DEINER AUSGABE. Schreibe ALLES in Japanisch (Kanji, Hiragana, Katakana). Auch Ortsnamen: 下北沢 nicht "Shimokitazawa".
  ABER: Der Spieler darf Romaji schreiben! Wenn {player_name} Romaji verwendet (z.B. "onakasuita", "ikou", "sugoi ne"),
  erkenne es als japanischen Versuch, verstehe die Bedeutung und reagiere natürlich auf Japanisch.
  Romaji-Eingabe zählt als Sprachbemühung (language_effort) — der Spieler versucht aktiv Japanisch, auch ohne japanische Tastatur.
- dialog_jp_furigana ist PFLICHT und NIEMALS leer. Es ist derselbe Text wie dialog_jp,
  aber mit Furigana-Klammern für JEDES Kanji.
  FORMAT: Kanji[Lesung] — das Kanji steht VOR der Klammer, die Hiragana-Lesung IN der Klammer.
  RICHTIG: 漢字[かんじ] 下北沢[しもきたざわ] 喉[のど]が渇[かわ]いた 食[た]べる
  FALSCH:  かんじ[漢字] のど[喉] — NIEMALS Hiragana vor der Klammer!
  Beispiel: dialog_jp = 「下北沢の駅で会いましょう！」
           dialog_jp_furigana = 「下北沢[しもきたざわ]の駅[えき]で会[あ]いましょう！」
  Auch Eigennamen brauchen Furigana: 林[はやし]あおい, 君[くん]
- dialog_de ist die genaue deutsche Übersetzung von dialog_jp — es gelten dieselben Regeln:
  NUR gesprochener Text, KEINE Handlungsbeschreibungen oder Erzählertext.
- Halte Dialoge kurz (1-3 Sätze)
- Passe die expression an den emotionalen Ton an
- POSE & STAGING: Wähle <pose> passend zur Körpersprache (nur aus der Posen-Liste;
  Tag weglassen, wenn keine Posen gelistet sind). <staging> ist Inszenierung:
  "left"/"center"/"right" für die Position, "near" für Nahaufnahmen bei intimen oder
  wichtigen Momenten (z.B. "right near"). Standard ist center in normaler Distanz —
  setze staging nur, wenn die Szene es wirklich verlangt, nicht in jeder Zeile.
- Führe die Geschichte natürlich basierend auf dem Input von {player_name} weiter
- Wenn {player_name} Japanisch versucht (egal ob in Kana, Kanji oder Romaji), reagiere ermutigend und korrigiere sanft.
  Bei Romaji-Eingabe: Zeige in error_correction die korrekte japanische Schreibweise (z.B. "onakasuita → お腹[おなか]が空[す]いた")
- ERROR_CORRECTION (der Tipp-Kasten für den Spieler):
  * NUR bei ECHTEN Fehlern setzen (falsche Grammatik, falsches Wort, falsche Partikel,
    unpassende Höflichkeitsstufe). War die Eingabe korrekt: Tag leer lassen.
  * Hiragana statt Kanji zu schreiben ist NIEMALS ein Fehler — beide Schreibweisen werden
    identisch ausgesprochen. Höchstens als kurze Info: "Man schreibt es üblicherweise お願[ねが]いします."
  * Sprich den Spieler DIREKT an ("Du kannst auch ... sagen"), niemals in der dritten Person
    und niemals als Szenenbeschreibung ("Kai hat ... verwendet, Aoi korrigiert ..." ist FALSCH).
  * Kurz und konkret: Was war falsch → wie ist es richtig → 1 Satz warum. Kein Lob,
    keine Meta-Kommentare — Ermutigung gehört in Aois Dialog, nicht in den Tipp.
- Baue neue Vokabeln und Grammatik schrittweise ein
- Passe Aois Verhalten an ihren aktuellen Zuneigungston an
- Wenn der Spieler Schwächen hat, baue diese Themen gezielt in den Dialog ein
- ANALYSIS: Bewerte JEDE Interaktion. Gib mastery_delta nur wenn ein Grammatik-Thema relevant ist.
  grammar_topic MUSS exakt einer dieser kanonischen Bezeichnungen entsprechen (sonst weglassen):
  {grammar_taxonomy}
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
- MEMORY: Bei scene_end=true ist <memory> PFLICHT: Fasse in 1-2 deutschen Sätzen zusammen,
  was in der Szene passiert ist (Ereignisse, wichtige persönliche Infos, Stimmung).
  Diese Zusammenfassungen sind Aois Langzeitgedächtnis — schreibe sie so, dass sie später
  als Erinnerung nützlich sind. Während laufender Szenen: <memory> weglassen.
- NEW_VOCAB: Wenn im Dialog neue oder wiederholte Lernvokabeln vorkommen, liste MAXIMAL 3
  im Format 言葉[よみ]=deutsche Bedeutung, mit | getrennt. Nur wirklich nützliche Alltagswörter,
  keine Partikeln oder Namen. Wenn nichts Neues vorkommt: Tag leer lassen oder weglassen.
- VOKABEL-WIEDERHOLUNG: Wenn oben fällige Vokabeln gelistet sind, webe 1-2 davon natürlich in
  Aois Dialog ein — oder lass Aoi spielerisch nachfragen ("weißt du noch, was ... heißt?").
  Nicht mehr als eine Abfrage pro Szene, es soll ein Gespräch bleiben, kein Vokabeltest.
- PROMISE: Wenn im Gespräch eine KONKRETE Verabredung oder ein Versprechen entsteht
  (z.B. "morgen um 10 am Schrein", "ich bringe dir das Foto mit"), setze <promise>.
  Wenn ein offenes Versprechen (siehe Spielstand) eingelöst wird, setze <promise_resolved>
  und belohne affection_reliability (+0.5 oder +1). Wird es vergessen oder gebrochen,
  setze ebenfalls <promise_resolved> und gib affection_reliability -0.5 oder -1.
"""

DEFAULT_PREMISE = """\
Der Spieler heißt {player_name} und ist auf einem Sabbatical in Shimokitazawa, Tokio.
Er hat Aoi (林あおい) online in einem Sprachaustausch-Forum kennengelernt.
Heute treffen sie sich zum ersten Mal persönlich. Aoi zeigt {player_name} die Gegend \
und hilft ihm, sein Japanisch in echten Alltagssituationen zu verbessern."""

# Register/difficulty rules per estimated JLPT level. Resolves the conflict
# between Aoi's character (casual + dialect) and learner level: at N5 she
# deliberately speaks simply and TEACHES casual forms instead of just using
# them — that fits her character (she loves teaching Japanese).
LEVEL_RULES = {
    "N5": (
        "- Kurze, einfache Sätze (max. ~12 Wörter), Grundwortschatz, klare です/ます-nahe Sprache.\n"
        "- Aoi darf einzelne Casual-Ausdrücke benutzen, erklärt sie dann aber kurz und begeistert "
        "(sie liebt es zu unterrichten). KEIN unkommentierter Slang oder Dialekt.\n"
        "- Höchstens 1 neues Grammatik-Muster pro Szene."
    ),
    "N4": (
        "- Natürliche, aber noch übersichtliche Sätze. Casual Speech ist jetzt Standard bei Aoi.\n"
        "- Slang und Saitama-Dialekt sparsam und mit kurzer Erklärung beim ersten Auftreten.\n"
        "- Baue gezielt N4-Grammatik ein (Konditionale, Potenzialform, あげる/くれる/もらう)."
    ),
    "N3": (
        "- Natürliches Japanisch in normalem Tempo, Casual Speech, Dialekt und Slang erlaubt.\n"
        "- Erkläre nur noch wirklich seltene Ausdrücke.\n"
        "- Fordere den Spieler: längere Antworten, Nuancen, indirekte Ausdrucksweisen."
    ),
}

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
        custom_premise: str | None = None,
        jlpt_level: str = "N5",
        memories: list[dict] | None = None,
        due_vocab: list[dict] | None = None,
        story_beat_block: str | None = None,
        available_poses: list[str] | None = None,
    ) -> str:
        aoi_expressions = ", ".join(CHARACTER_EXPRESSIONS.get("aoi", ["neutral"]))
        tone_desc = TONE_DESCRIPTIONS.get(aoi_tone, TONE_DESCRIPTIONS["neutral"])
        tone_desc = tone_desc.format(player_name=player_name)

        if weak_points:
            weak_points_info = f"Der Spieler hat Schwierigkeiten mit: {', '.join(weak_points)}\nBaue diese Themen gezielt in den Dialog ein."
        else:
            weak_points_info = "Keine bekannten Schwächen. Führe grundlegende Themen ein."

        backgrounds = ", ".join(self.get_background_ids())

        premise = custom_premise if custom_premise else DEFAULT_PREMISE.format(player_name=player_name)

        level_rules = LEVEL_RULES.get(jlpt_level, LEVEL_RULES["N5"])
        grammar_taxonomy = ", ".join(taxonomy_for_level(jlpt_level))

        # Conditional blocks: omitted entirely when empty to save tokens.
        memory_block = ""
        if memories:
            mem_lines = "\n".join(
                f"- Tag {m['day']}: {m['text']}" for m in memories
            )
            memory_block = (
                "LANGZEIT-ERINNERUNGEN (was bisher geschah — beziehe dich "
                "natürlich darauf, Aoi erinnert sich an alles hier):\n"
                f"{mem_lines}\n\n"
            )

        vocab_block = ""
        if due_vocab:
            vocab_lines = " | ".join(
                f"{v['word']}[{v['reading']}]={v['meaning_de']}" if v.get("reading")
                else f"{v['word']}={v['meaning_de']}"
                for v in due_vocab
            )
            vocab_block = (
                "FÄLLIGE VOKABELN (zum natürlichen Wiederholen, siehe Regel "
                f"VOKABEL-WIEDERHOLUNG): {vocab_lines}\n\n"
            )

        story_block = ""
        if story_beat_block:
            story_block = f"{story_beat_block}\n\n"

        pose_block = ""
        if available_poses:
            pose_block = (
                f"VERFÜGBARE POSEN FÜR AOI:\n{', '.join(available_poses)}\n\n"
            )

        return SYSTEM_PROMPT_TEMPLATE.format(
            premise=premise,
            character_info=self.aoi_sheet,
            aoi_tone=aoi_tone,
            tone_description=tone_desc,
            weak_points_info=weak_points_info,
            jlpt_level=jlpt_level,
            level_rules=level_rules,
            grammar_taxonomy=grammar_taxonomy,
            memory_block=memory_block,
            vocab_block=vocab_block,
            story_block=story_block,
            pose_block=pose_block,
            aoi_expressions=aoi_expressions,
            available_backgrounds=backgrounds,
            game_state_summary=game_state_summary,
            player_name=player_name,
        )

    @staticmethod
    def _clean_history_content(content: str) -> str:
        """Strip non-conversational XML blocks from old-format assistant history.

        Older history entries may contain full XML responses including
        <analysis> and <scene_status> blocks.  These are game-engine
        metadata and clutter the conversational context that Claude sees,
        leading to confused responses.  This method strips them and keeps
        only the <scene> dialog content.
        """
        # Remove <analysis>...</analysis>
        content = re.sub(r'\s*<analysis>.*?</analysis>', '', content, flags=re.DOTALL)
        # Remove <scene_status>...</scene_status>
        content = re.sub(r'\s*<scene_status>.*?</scene_status>', '', content, flags=re.DOTALL)
        # Remove non-essential visual-only fields inside <scene>
        content = re.sub(r'\s*<expression>.*?</expression>', '', content, flags=re.DOTALL)
        content = re.sub(r'\s*<background>.*?</background>', '', content, flags=re.DOTALL)
        content = re.sub(r'\s*<dialog_jp_furigana>.*?</dialog_jp_furigana>', '', content, flags=re.DOTALL)
        return content.strip()

    async def generate_scene(
        self,
        user_input: str,
        game_state_summary: str,
        conversation_history: list[dict],
        aoi_tone: str = "neutral",
        weak_points: list[str] | None = None,
        player_name: str = "Spieler",
        custom_premise: str | None = None,
        jlpt_level: str = "N5",
        memories: list[dict] | None = None,
        due_vocab: list[dict] | None = None,
        story_beat_block: str | None = None,
        available_poses: list[str] | None = None,
    ) -> SceneData:
        system_prompt = self._build_system_prompt(
            game_state_summary, aoi_tone, weak_points,
            player_name=player_name, custom_premise=custom_premise,
            jlpt_level=jlpt_level, memories=memories,
            due_vocab=due_vocab, story_beat_block=story_beat_block,
            available_poses=available_poses,
        )

        messages = []
        for turn in conversation_history:
            content = turn["content"]
            # Clean old-format assistant entries that still contain full XML
            if turn["role"] == "assistant":
                content = self._clean_history_content(content)
            messages.append({
                "role": turn["role"],
                "content": content,
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
        player_name: str = "Spieler",
        custom_premise: str | None = None,
        jlpt_level: str = "N5",
        memories: list[dict] | None = None,
        due_vocab: list[dict] | None = None,
        story_beat_block: str | None = None,
        available_poses: list[str] | None = None,
    ) -> SceneData:
        try:
            return await self.generate_scene(
                user_input, game_state_summary, conversation_history,
                aoi_tone, weak_points, player_name=player_name,
                custom_premise=custom_premise,
                jlpt_level=jlpt_level, memories=memories,
                due_vocab=due_vocab, story_beat_block=story_beat_block,
                available_poses=available_poses,
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
