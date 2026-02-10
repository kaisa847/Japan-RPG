# Japanese Life: Tokyo Stories

Visual Novel Engine for a Japanese-learning RPG. The player (Kai) lives in a sharehouse in Tokyo and learns Japanese through NPC interactions. Uses Claude API for dynamic story generation.

## Setup

### Prerequisites
- Python 3.11+
- Anthropic API Key

### Installation

```bash
pip install -r backend/requirements.txt
```

### Configuration

Set your API key in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Generate Placeholder Assets

```bash
python generate_placeholders.py
```

### Run

```bash
uvicorn backend.main:app --reload --port 8000
```

Open `http://localhost:8000` in your browser.

### Tests

```bash
pytest backend/tests/ -v
```

## Project Structure

```
├── backend/
│   ├── main.py              # FastAPI server
│   ├── claude_handler.py    # Anthropic API wrapper
│   ├── response_parser.py   # XML scene parser
│   ├── state_manager.py     # Game state persistence
│   └── tests/
├── frontend/
│   ├── index.html           # Main page
│   ├── engine.js            # VN rendering engine
│   ├── style.css            # Styling
│   └── config.js            # Constants
├── assets/
│   ├── characters/          # Character sprites (400x800px)
│   └── backgrounds/         # Background images (1920x1080px)
├── data/
│   └── characters/          # Character sheet markdown files
├── generate_placeholders.py # Asset placeholder generator
└── .env                     # API key (not committed)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/generate_scene` | Generate next scene from user input |
| GET | `/game_state` | Get current game state |
| POST | `/game_state/reset` | Reset to initial state |
| GET | `/api/assets/available` | List available character sprites and backgrounds |

## Characters

| ID | Name | Room |
|----|------|------|
| aoi | Hayashi Aoi (22F) | 203 |
| tanaka_kenji | Tanaka Kenji (68M) | 101 |
| yamada_rina | Yamada Rina (29F) | 102 |
| min_jun | Park Min-jun (25M) | 201 |
| sato_sachiko | Sato Sachiko (20F) | 202 |
