# Japanese Life: Tokyo Stories

Ein KI-gesteuertes Visual Novel, das deutschsprachigen Spielern Japanisch beibringt. Der Spieler (Kai) trifft sich mit Aoi in Shimokitazawa, Tokio, und lernt durch natuerliche Gespraeche und gemeinsame Aktivitaeten Japanisch. Jede Szene wird dynamisch von Claude (Anthropic) generiert.

## Spielkonzept

Kai ist auf einem Sabbatical in Tokio und hat Aoi (林あおい, 22, Kulturanthropologie-Studentin an der Waseda) in einem Online-Sprachaustausch-Forum kennengelernt. Das Spiel beginnt mit ihrem ersten persoenlichen Treffen am Bahnhof Shimokitazawa. Von dort aus erkundet der Spieler gemeinsam mit Aoi die Gegend -- Cafes, Ramen-Shops, Vintage-Laeden, Schreine und mehr.

Der Spieler tippt frei, was Kai sagen oder tun soll (auf Deutsch oder Japanisch). Claude generiert daraufhin Aois Reaktion mit japanischem Dialog, Furigana, deutscher Uebersetzung und optionaler Grammatik-Korrektur.

## Features

### Dynamische KI-Erzaehlung
- Freie Texteingabe statt vorgefertigter Dialogoptionen
- Claude generiert kontextabhaengige Szenen mit Charakter, Ausdruck, Hintergrund und Dialog
- Natuerliche Gespraechsfuehrung mit Erzaehler-Einschueben fuer Szenenbeschreibungen
- Aoi schlaegt nach natuerlichen Gespraechsenden 2-3 neue Orte/Aktivitaeten vor

### Japanisch-Lernsystem
- **Furigana-Anzeige:** Jedes Kanji hat eine Lesung in Klammern, dargestellt als Ruby-Text (ein/ausschaltbar)
- **Deutsche Uebersetzung:** Jeder japanische Dialog wird uebersetzt (ein/ausschaltbar)
- **Fehlerkorrektur:** Wenn der Spieler Japanisch versucht, korrigiert Aoi sanft und erklaerend
- **Kanonische Grammatik-Taxonomie:** Grammatikthemen kommen aus einer festen N5/N4-Liste (`backend/grammar_taxonomy.py`); Freitext-Varianten werden normalisiert, unbekannte Themen verworfen — das Tracking fragmentiert nicht
- **Grammatik-Tracking:** Erkannte Grammatikthemen werden mit Mastery-Wert (0-100%) getrackt
- **Schwachstellen-System:** Die 5 schwaechsten Themen werden erkannt und gezielt in zukuenftige Dialoge eingebaut
- **JLPT-Ableitung:** Das Level (N5 → N4 → N3) wird aus der tatsaechlichen Mastery der kanonischen Themen berechnet, nicht geschaetzt
- **Niveau-Steuerung:** Aois Sprachregister haengt am Level: Bei N5 spricht sie bewusst einfach und erklaert Casual-Ausdruecke; Slang und Saitama-Dialekt kommen erst mit steigendem Niveau dazu
- **Vokabelheft:** Neue Woerter aus den Dialogen werden gesammelt (max. 300); schwache, laenger nicht gesehene Woerter werden Claude als "faellig" mitgegeben und natuerlich im Gespraech wiederholt (verdecktes Spaced Repetition). Einsehbar im Stats-Panel

### Story-System
- **Story-Arc "Hayashiya":** 10 geskriptete Story-Beats rund um Aois Konflikt mit dem Familienrestaurant in Kawagoe (Draft: `data/story/story_arc.md`, Beats: `data/story/beats.json`)
- **Trigger:** Beats aktivieren sich ueber Tag, Zuneigungs-Score und Story-Flags; es ist immer hoechstens ein Beat aktiv, nur dessen kurze Regieanweisung wandert in den Prompt
- **Organisch statt erzwungen:** Die KI webt den Beat ein, wenn es passt; wechselt der Spieler das Thema, bleibt der Beat aktiv und wird spaeter erneut versucht
- **Abschluss-Meldung:** Die KI meldet `<story_flag>` erst, wenn der Beat im Dialog tatsaechlich stattgefunden hat; das Backend akzeptiert nur das Flag des aktiven Beats

### Episodisches Gedaechtnis
- Bei jedem Szenenende fasst die KI die Szene in 1-2 Saetzen zusammen (`<memory>`)
- Die letzten 12 Zusammenfassungen (je max. 240 Zeichen) werden als Langzeitgedaechtnis in den System-Prompt injiziert — Aoi erinnert sich damit ueber Tage hinweg an Ereignisse, bei fest gedeckelten Token-Kosten

### Versprechen-System
- Konkrete Verabredungen ("morgen um 10 am Schrein") werden als offene Versprechen gespeichert (max. 3) und der KI im Spielstand mitgegeben
- Eingeloeste Versprechen belohnen den Zuverlaessigkeits-Faktor, gebrochene senken ihn — damit ist `reliability` erstmals bespielbar und das Zeitsystem bekommt Spielbedeutung

### Zuneigungssystem (Affection)
Aois Verhalten aendert sich basierend auf 5 gewichteten Faktoren:

| Faktor | Gewicht | Beschreibung |
|--------|---------|--------------|
| Sprachbemuehung | 35% | Wie sehr sich Kai um Japanisch bemueht |
| Kulturelles Interesse | 25% | Interesse an japanischer Kultur |
| Persoenliche Bindung | 20% | Emotionale Naehe und Vertrauen |
| Humor | 10% | Gemeinsames Lachen und Witz |
| Zuverlaessigkeit | 10% | Konstanz und Verlaesslichkeit |

Daraus ergibt sich Aois Ton:

| Score | Ton | Verhalten |
|-------|-----|-----------|
| 0-19 | Distanziert | Hoeflich, verwendet Keigo, haelt Distanz |
| 20-39 | Neutral | Freundlich, hilfsbereit, noch etwas formell |
| 40-59 | Freundlich | Entspannt, Casual Speech, teilt persoenliche Geschichten |
| 60-79 | Warmherzig | Herzlich, fuersorglich, zeigt echtes Interesse |
| 80-100 | Vertraut | Sehr vertraut, neckt Kai liebevoll, teilt Geheimnisse |

Affection-Deltas pro Interaktion werden auf +/-1 geclampt und mit Faktor 0.5 gedaempft, sodass die Entwicklung graduell verlaeuft.

### Zeitsystem
- Tages- und Stundenzaehler mit 7 Tageszeiten (Fruehmorgen, Morgen, Mittag, Nachmittag, Abend, Nacht, Spaetnacht)
- Zeit schreitet mit Aktivitaeten voran (Cafebesuch ~1-2h, Einkaufsbummel ~2-3h, Abendessen ~2h)
- Backend-Fallback: Wenn eine Szene endet aber kein Zeitupdate kommt, wird automatisch +1h gesetzt
- Periodischer Fallback: Nach 6 Gespraechsrunden ohne Zeitaenderung rueckt die Zeit automatisch 1h vor
- Tageswechsel fuer laengere Spielsessions (`next_day` springt auf 9:00 Uhr morgens)

### Visual Novel Engine
- **Typewriter-Effekt:** Dialog erscheint Zeichen fuer Zeichen (30ms pro Zeichen)
- **12 Charakter-Ausdruecke:** neutral, happy, excited, curious, talking, laughing, surprised, thinking, embarrassed, determined, worried, sleepy
- **16 Hintergruende:** Orte in Shimokitazawa und Umgebung
- **Ueberblendungen:** Sanfte Fade-Uebergaenge (300ms) fuer Hintergrund- und Charakterwechsel
- **Asset-Caching:** Bilder werden vorab geladen und gecacht
- **Szenen-Navigation:** Zurueckblaettern durch vergangene Szenen (bis zu 100 gespeichert)

### Speichersystem
- 9 nummerierte Speicherplaetze pro Benutzer
- Automatischer Name (z.B. "Tag 3 - cafe_shimokitazawa") oder benutzerdefiniert
- Vollstaendiger Spielstand-Snapshot inkl. Zuneigung, Lernfortschritt, Gespraechsverlauf und Szenen-Historie
- Speichern, Laden und Loeschen ueber das Ingame-Menue

### Benutzerverwaltung
- Mehrere Benutzer mit isolierten Spielstaenden
- JWT-basierte Authentifizierung (7 Tage gueltig)
- Admin-Funktionen zur Benutzererstellung
- Passwort-Hashing mit bcrypt

### Stats-Anzeige
- Zuneigungswerte mit farbcodierten Balken pro Faktor (inkl. Gewichtung)
- Grammatik-Themen sortiert nach Mastery (schwaechste zuerst)
- JLPT-Level-Badge
- Interaktionszaehler

## Setup

### Voraussetzungen
- Python 3.11+
- Anthropic API Key

### Installation

```bash
pip install -r backend/requirements.txt
```

### Konfiguration

API-Key in `.env` setzen:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Optional ein anderes Claude-Modell waehlen (Standard: `claude-sonnet-4-5-20250929`):

```
CLAUDE_MODEL=claude-sonnet-4-5-20250929
```

### Schnellstart

```bash
pip install -r backend/requirements.txt   # Abhaengigkeiten installieren
python generate_placeholders.py            # Platzhalter-Grafiken erstellen
python -m backend.create_user admin --admin # Ersten Admin-Benutzer anlegen
python run.py                              # Server starten
```

Oeffne `http://localhost:8000` im Browser. Der Server leitet automatisch zur Login-Seite weiter.

## CLI-Referenz

### `run.py` -- Entwicklungsserver

Startet den FastAPI-Server auf Port 8000.

```bash
python run.py              # Mit Auto-Reload (benoetigt watchfiles)
python run.py --no-reload  # Ohne Auto-Reload
```

| Option | Beschreibung |
|--------|--------------|
| *(ohne)* | Startet mit File-Watcher, der bei Aenderungen an `.py`, `.js`, `.css`, `.html` in `backend/` und `frontend/` automatisch neustartet. Benoetigt `watchfiles` (`pip install watchfiles`). Faellt ohne `watchfiles` automatisch auf einfachen Modus zurueck. |
| `--no-reload` | Startet den Server einmalig ohne File-Watching. |

**Netzwerk:** Lauscht auf `0.0.0.0:8000` (erreichbar von allen Netzwerkschnittstellen).

Alternativ direkt mit uvicorn (mehr Kontrolle ueber Host/Port):

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### `backend/create_user.py` -- Benutzerverwaltung

Erstellt einen neuen Benutzer fuer das Spiel. Fragt interaktiv nach dem Passwort.

```bash
python -m backend.create_user <benutzername> [--admin]
```

| Argument | Beschreibung |
|----------|--------------|
| `benutzername` | Pflicht. 3-20 Zeichen, nur Buchstaben, Ziffern und Unterstriche. Wird als Kleinbuchstaben gespeichert. |
| `--admin` | Optional. Gibt dem Benutzer Admin-Rechte (kann ueber die API weitere Benutzer erstellen und auflisten). |

**Passwort-Regeln:** Mindestens 4 Zeichen, muss zweimal identisch eingegeben werden.

**Beispiele:**

```bash
# Ersten Admin-Benutzer erstellen (empfohlen als erster Schritt)
python -m backend.create_user admin --admin

# Normalen Spieler erstellen
python -m backend.create_user kai

# Weiterer Spieler
python -m backend.create_user player2
```

Benutzer werden in `data/users.json` gespeichert. Jeder Benutzer erhaelt einen eigenen Spielstand-Ordner unter `data/users/<benutzername>/`.

### `generate_placeholders.py` -- Asset-Generierung

Generiert farbcodierte Platzhalter-Grafiken fuer Entwicklung und Tests.

```bash
python generate_placeholders.py
```

Keine Optionen. Erzeugt:
- **Charakter-Sprites** in `assets/characters/<id>/` (400x800px, RGBA PNG) -- einfache Silhouetten mit Farbkennung und Expression-Label
- **Hintergruende** in `assets/backgrounds/` (1920x1080px, RGB PNG) -- einfarbige Flaechen mit Farbverlauf und Orts-Label

Benutzt Pillow (PIL). Farben pro Charakter: Aoi (Kornblumenblau), Tanaka (Olivgruen), Rina (Grau), Min-jun (Anthrazit), Sachiko (Pastellrosa).

Diese Platzhalter koennen jederzeit durch echte Grafiken ersetzt werden -- das Spiel erkennt automatisch vorhandene PNG/JPG/WEBP-Dateien ueber den `/api/assets/available`-Endpunkt.

### `pytest` -- Tests ausfuehren

```bash
pytest backend/tests/ -v                    # Alle Tests
pytest backend/tests/test_state_manager.py  # Nur Spielzustand-Tests
pytest backend/tests/test_auth.py           # Nur Auth-Tests
pytest backend/tests/test_response_parser.py # Nur Parser-Tests
pytest backend/tests/test_integration.py    # Nur API-Integrationstests
pytest backend/tests/ -v -k "time"          # Nur Tests mit "time" im Namen
```

Testet: Authentifizierung (JWT, bcrypt, User-CRUD), Spielzustandsverwaltung (Laden, Speichern, Reset), XML-Parsing (Szenen, Analyse, Scene-Status inkl. Memory/Vokabeln/Story-Flags/Versprechen), Furigana-Korrektur (vertauschte Notation), Zeitsystem (Stunden, Tage, Perioden, periodischer Fallback), Zuneigungssystem (Gewichtung, Clamping, Daempfung, Tonstufen), Grammatik-Taxonomie (Normalisierung, JLPT-Ableitung), Story-Engine (Beat-Trigger, Abschluss), episodisches Gedaechtnis, Vokabelheft, Versprechen, Speicherplaetze (CRUD, Snapshot-Integritaet) und alle API-Endpunkte.

## Projektstruktur

```
Japan-RPG/
├── backend/
│   ├── main.py                # FastAPI-Server, alle API-Endpunkte
│   ├── claude_handler.py      # Anthropic-API-Integration, System-Prompt-Aufbau
│   ├── response_parser.py     # XML-Szenen-Parser, Furigana-Korrektur
│   ├── state_manager.py       # Spielzustand: Zeit, Zuneigung, Lernen, Speicherplaetze
│   ├── grammar_taxonomy.py    # Kanonische N5/N4-Themen, JLPT-Ableitung
│   ├── story_engine.py        # Story-Beat-Auswahl und Prompt-Block
│   ├── auth.py                # JWT-Authentifizierung, Benutzerverwaltung
│   ├── create_user.py         # CLI-Tool zur Benutzererstellung
│   └── tests/
│       ├── test_auth.py              # Auth + JWT Tests
│       ├── test_integration.py       # API-Endpunkt-Tests
│       ├── test_response_parser.py   # XML-Parsing + Furigana Tests
│       ├── test_state_manager.py     # State, Zeit, Affection, Save/Load Tests
│       ├── test_grammar_taxonomy.py  # Taxonomie + JLPT Tests
│       ├── test_story_engine.py      # Story-Beat-Trigger Tests
│       └── test_memory_vocab.py      # Memory, Vokabeln, Versprechen Tests
├── frontend/
│   ├── index.html             # Spiel-UI (Dialog, HUD, Menues)
│   ├── login.html             # Login-Seite
│   ├── engine.js              # Visual Novel Rendering Engine
│   ├── auth.js                # JWT-Token-Management
│   ├── config.js              # UI-Konstanten und Konfiguration
│   └── style.css              # Vollstaendiges Styling
├── data/
│   ├── start_prompt.txt       # Startszene-Regieanweisung
│   ├── story/
│   │   ├── story_arc.md       # Story-Draft: Arc 1 "Hayashiya" (3 Akte, 10 Beats)
│   │   └── beats.json         # Maschinenlesbare Story-Beats mit Triggern
│   └── characters/
│       ├── aoi.md             # Aoi Charakter-Sheet (Persoenlichkeit, Verhalten)
│       ├── aoi.visual.md      # Visuelle Referenz fuer Asset-Erstellung
│       └── _archive/          # Vorbereitete Charakter-Sheets (zukuenftige NPCs)
├── assets/                    # Grafiken (nicht im Git, per generate_placeholders.py erstellt)
│   ├── characters/aoi/       # 12 Expression-Sprites (PNG, 400x800px)
│   └── backgrounds/           # 16 Ort-Hintergruende (PNG, 1920x1080px)
├── generate_placeholders.py   # Platzhalter-Asset-Generator (Pillow)
├── run.py                     # Entwicklungsserver mit optionalem Auto-Reload
└── .env                       # API-Key (nicht im Git)
```

## API-Endpunkte

### Authentifizierung

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| POST | `/api/auth/login` | Login (OAuth2 Password Form) |
| GET | `/api/auth/me` | Aktuellen Benutzer verifizieren |
| POST | `/api/admin/users` | Neuen Benutzer erstellen (nur Admin) |
| GET | `/api/admin/users` | Alle Benutzer auflisten (nur Admin) |

### Spielzustand

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET | `/game_state` | Kompletter Spielzustand (Zeit, Ort, Zuneigung, Lernfortschritt, letzte Szene) |
| POST | `/game_state/reset` | Neues Spiel starten (archiviert aktuelle Session) |
| GET | `/api/start_prompt` | Startszene-Regieanweisung laden |
| GET | `/api/scene_history` | Szenen-Historie abrufen (max. 100 Eintraege) |

### Szenengenerierung

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| POST | `/generate_scene` | Naechste Szene generieren |

**Input:** `{ "user_input": "..." }`

**Output:** Charakter, Ausdruck, Hintergrund, japanischer Dialog, Furigana, deutsche Uebersetzung, Analyse (Grammatik-Thema, Mastery-Delta, Fehlerkorrektur, Affection-Deltas), Szenen-Status (Zeitupdate, Szenen-Ende, Ortsvorschlaege), aktualisierte Zuneigungswerte und Uhrzeit.

### Speicherplaetze

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET | `/api/save_slots` | Alle Speicherplaetze auflisten |
| POST | `/api/save_slots/{id}` | In Slot speichern (1-9), optional mit Name |
| POST | `/api/save_slots/{id}/load` | Spielstand aus Slot laden |
| DELETE | `/api/save_slots/{id}` | Speicherplatz loeschen |

### Assets

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET | `/api/assets/available` | Verfuegbare Charakter-Sprites und Hintergruende |

## Claude-Antwortformat

Jede KI-generierte Szene folgt diesem XML-Schema:

```xml
<scene>
  <character>aoi</character>           <!-- leer fuer Erzaehler -->
  <expression>happy</expression>
  <background>cafe_shimokitazawa</background>
  <dialog_jp>今日はいい天気ですね！</dialog_jp>
  <dialog_jp_furigana>今日[きょう]はいい天気[てんき]ですね！</dialog_jp_furigana>
  <dialog_de>Heute ist schoenes Wetter!</dialog_de>
</scene>

<analysis>
  <grammar_topic>です/ます-Form</grammar_topic>
  <mastery_delta>+0.1</mastery_delta>
  <error_correction>Erklaerung falls Fehler</error_correction>
  <affection_language_effort>+0.5</affection_language_effort>
  <affection_cultural_interest>0</affection_cultural_interest>
  <affection_personal_bond>0</affection_personal_bond>
  <affection_humor>0</affection_humor>
  <affection_reliability>0</affection_reliability>
</analysis>

<scene_status>
  <time_update>+1h</time_update>             <!-- +Nh oder next_day, Pflichtfeld -->
  <scene_end>false</scene_end>               <!-- true bei natuerlichem Szenenende -->
  <suggested_next>park|ramen_shop</suggested_next>  <!-- nur bei scene_end=true -->
  <memory>Kurze Szenen-Zusammenfassung</memory>     <!-- Pflicht bei scene_end=true -->
  <new_vocab>駅[えき]=Bahnhof|喉[のど]=Hals</new_vocab>  <!-- 0-3 Vokabeln, optional -->
  <story_flag>family_story_told</story_flag>  <!-- nur wenn der aktive Story-Beat stattfand -->
  <promise>Morgen um 10 am Schrein</promise>  <!-- neue Verabredung, optional -->
  <promise_resolved>Morgen um 10 am Schrein</promise_resolved>  <!-- eingeloest/gebrochen -->
</scene_status>
```

Der Response-Parser korrigiert automatisch:
- Vertauschte Furigana-Notation (z.B. `のど[喉]` wird zu `喉[のど]`)
- Fehlende Furigana (Fallback auf `dialog_jp`)
- Ungueltige Expressions (Fallback auf `neutral`)
- Leerer `<character>`-Tag wird als Erzaehler interpretiert

## Verfuegbare Hintergruende

`apartment_room`, `shimokitazawa_station`, `shimokitazawa_street`, `cafe_shimokitazawa`, `ramen_shop`, `vintage_shop`, `record_store`, `bookshop`, `park`, `shrine`, `convenience_store`, `train_station`, `izakaya`, `karaoke`, `temple`, `rooftop`

## Charakter: Aoi (林あおい)

| | |
|---|---|
| **Alter** | 22 |
| **Beruf** | Studentin (Kulturanthropologie, Waseda) |
| **Herkunft** | Saitama, lebt seit 3 Jahren in Shimokitazawa |
| **Persoenlichkeit** | Extrovertiert, neugierig, redselig, impulsiv |
| **Sprachstil** | Casual Speech (だ/である), Saitama-Dialekt, Tokioter Slang |
| **Lieblingsorte** | Stammcafe, Vintage-Plattenladen, Ramen-Shop, Schrein am Huegel |

**12 Ausdruecke:** neutral, happy, excited, curious, talking, laughing, surprised, thinking, embarrassed, determined, worried, sleepy

Weitere Charaktere sind als Charakter-Sheets in `data/characters/_archive/` vorbereitet.

## Technologie

| Komponente | Technologie |
|------------|-------------|
| Frontend | Vanilla JS (ES6+), HTML5, CSS3 |
| Backend | FastAPI (Python 3.11+) |
| KI | Claude API (Anthropic SDK) |
| Auth | JWT (PyJWT, HS256) + bcrypt |
| Persistenz | JSON-Dateien (pro Benutzer isoliert) |
| Validierung | Pydantic v2 |
| Tests | pytest + pytest-asyncio + httpx |
| Asset-Generierung | Pillow |
| Server | Uvicorn (ASGI) |

## Datenstruktur

Spielzustaende werden pro Benutzer als JSON gespeichert:

```
data/
├── users.json                          # Benutzer-Datenbank (Hashes, Rollen)
├── .jwt_secret                         # JWT-Secret (auto-generiert beim ersten Start)
└── users/{benutzername}/
    ├── game_state.json                 # Aktueller Spielzustand
    ├── session_log.json                # Archiv abgeschlossener Sessions
    └── saves/
        └── slot_{1-9}.json            # Speicherplaetze (vollstaendige Snapshots)
```

Jeder `game_state.json` enthaelt:
- **time:** Tag, Stunde, Tageszeit, Rundenzaehler seit letzter Zeitaenderung
- **current_location / current_background:** Aktueller Ort und Hintergrund-ID
- **affection:** 5 Zuneigungsfaktoren (je 0.0-100.0) mit gewichtetem Score und Ton
- **learning:** JLPT-Level (abgeleitet), Themen-Mastery-Map (kanonisch), Top-5-Schwachstellen, Interaktionszaehler, Vokabelheft
- **conversation_history:** Letzte 16 Gespraechsrunden (Kurzzeitkontext fuer Claude; Langzeitkontinuitaet kommt aus den Memories)
- **memories:** Letzte 12 Szenen-Zusammenfassungen (Langzeitgedaechtnis, je max. 240 Zeichen)
- **story:** Abgeschlossene Story-Beats
- **open_promises:** Offene Verabredungen/Versprechen (max. 3, speisen den Zuverlaessigkeits-Faktor)
- **scene_history:** Letzte 100 gerenderte Szenen (fuer Zurueckblaettern im Frontend)
- **last_scene:** Zuletzt angezeigte Szene (fuer UI-Wiederherstellung nach Page-Reload)
- **flags:** Story-Flags (werden von der Story-Engine gesetzt und von Beat-Triggern gelesen)

### Token-Budget

Die Erweiterungen sind so gebaut, dass die API-Kosten pro Request gedeckelt bleiben:
- Alle neuen Prompt-Bloecke (Memories, faellige Vokabeln, Story-Beat) sind **konditional** — leere Bloecke kosten nichts
- Harte Caps: 12 Memories x 240 Zeichen, max. 5 faellige Vokabeln, genau 1 aktiver Story-Beat (2-4 Saetze), max. 3 offene Versprechen
- Die Grammatik-Taxonomie im Prompt waechst mit dem Level (N5-Spieler sehen nur die N5-Liste)
- Gegenfinanzierung: Conversation-History von 20 auf 16 Runden reduziert (die Memories ersetzen die verlorene Kontinuitaet guenstiger)
