"""Generate placeholder assets for all characters and backgrounds."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Character colors (unique per character, matching their personality)
CHARACTER_COLORS = {
    "aoi": (100, 149, 237),          # cornflower blue
    "tanaka_kenji": (107, 142, 35),  # olive green
    "yamada_rina": (119, 119, 136),  # muted gray
    "min_jun": (50, 50, 60),         # dark charcoal
    "sato_sachiko": (219, 160, 190), # pastel pink
}

# Per-character expressions from character sheets
CHARACTER_EXPRESSIONS = {
    "aoi": [
        "neutral", "happy", "excited", "curious", "talking",
        "laughing", "surprised", "thinking", "embarrassed",
        "determined", "worried", "sleepy",
    ],
    "tanaka_kenji": [
        "neutral", "gentle_smile", "concerned", "explaining",
        "amused", "thoughtful", "proud", "surprised",
        "tired", "serious", "sad", "working",
    ],
    "yamada_rina": [
        "neutral", "tired", "amused", "deadpan", "talking",
        "sarcastic", "concerned", "annoyed", "surprised",
        "exhausted", "focused", "slight_smile",
    ],
    "min_jun": [
        "neutral", "slight_smile", "tired", "focused", "annoyed",
        "amused", "thinking", "uncomfortable", "surprised",
        "working", "protective", "sleepy",
    ],
    "sato_sachiko": [
        "neutral", "polite_smile", "embarrassed", "excited",
        "worried", "thinking", "dreamy", "surprised",
        "shy", "happy", "apologetic", "focused",
    ],
}

# Display names
CHARACTER_DISPLAY = {
    "aoi": "Aoi",
    "tanaka_kenji": "Tanaka",
    "yamada_rina": "Rina",
    "min_jun": "Min-jun",
    "sato_sachiko": "Sachiko",
}

BACKGROUNDS = {
    "room_204": (70, 70, 100, "Zimmer 204 (Kai)"),
    "room_203": (75, 75, 110, "Zimmer 203 (Aoi)"),
    "room_202": (80, 70, 100, "Zimmer 202 (Sachiko)"),
    "room_201": (60, 60, 80, "Zimmer 201 (Min-jun)"),
    "room_102": (65, 65, 75, "Zimmer 102 (Rina)"),
    "room_101": (85, 80, 70, "Zimmer 101 (Tanaka)"),
    "sakura_house_living": (120, 100, 80, "Wohnzimmer"),
    "sakura_house_kitchen": (140, 120, 90, "Kueche"),
    "sakura_house_entrance": (100, 110, 100, "Eingang"),
    "sakura_house_garden": (80, 130, 70, "Garten"),
    "campus_entrance": (100, 140, 120, "Campus"),
    "classroom_101": (160, 150, 130, "Klassenzimmer"),
    "cafeteria": (180, 140, 100, "Cafeteria"),
    "library": (100, 85, 70, "Bibliothek"),
    "convenience_store": (200, 200, 180, "Konbini"),
    "train_station": (140, 140, 160, "Bahnhof"),
    "park": (70, 140, 70, "Park"),
    "shopping_street": (170, 130, 120, "Einkaufsstrasse"),
    "shrine": (140, 110, 90, "Schrein"),
}


def get_font(size: int):
    """Try to load a TrueType font, fall back to default."""
    try:
        return ImageFont.truetype("arial.ttf", size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except (OSError, IOError):
            return ImageFont.load_default()


def generate_character_placeholder(
    name: str, display_name: str, color: tuple, expression: str, output_dir: Path
) -> None:
    img = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    r, g, b = color

    # Head (ellipse)
    draw.ellipse([130, 40, 270, 200], fill=(r, g, b, 220))

    # Body (rounded rectangle)
    draw.rounded_rectangle(
        [110, 190, 290, 720], radius=20, fill=(r, g, b, 180)
    )

    # Legs
    draw.rectangle([130, 700, 185, 790], fill=(r, g, b, 160))
    draw.rectangle([215, 700, 270, 790], fill=(r, g, b, 160))

    # Name label at top
    font_name = get_font(16)
    draw.text(
        (200, 10), display_name, fill=(255, 255, 255, 220),
        anchor="mt", font=font_name,
    )

    # Expression label at bottom
    font_expr = get_font(13)
    draw.text(
        (200, 770), expression, fill=(255, 255, 255, 180),
        anchor="mm", font=font_expr,
    )

    img.save(output_dir / f"{expression}.png", "PNG")


def generate_background_placeholder(
    bg_id: str, color: tuple, label: str, output_dir: Path
) -> None:
    r, g, b = color
    img = Image.new("RGB", (1920, 1080), (r, g, b))
    draw = ImageDraw.Draw(img)

    # Subtle gradient overlay (floor)
    for y in range(700, 1080):
        factor = (y - 700) / 380
        floor_r = int(r * (1 - factor * 0.3))
        floor_g = int(g * (1 - factor * 0.3))
        floor_b = int(b * (1 - factor * 0.3))
        draw.line([(0, y), (1919, y)], fill=(floor_r, floor_g, floor_b))

    # Label
    font = get_font(36)
    draw.text(
        (960, 200), label, fill=(255, 255, 255, 180),
        anchor="mm", font=font,
    )

    # ID
    font_small = get_font(18)
    draw.text(
        (960, 250), f"[{bg_id}]", fill=(200, 200, 200),
        anchor="mt", font=font_small,
    )

    img.save(output_dir / f"{bg_id}.png", "PNG")


def main():
    base = Path("assets")

    # Characters
    for char_id, color in CHARACTER_COLORS.items():
        char_dir = base / "characters" / char_id
        char_dir.mkdir(parents=True, exist_ok=True)
        display = CHARACTER_DISPLAY.get(char_id, char_id)
        expressions = CHARACTER_EXPRESSIONS.get(char_id, ["neutral"])
        for expr in expressions:
            generate_character_placeholder(char_id, display, color, expr, char_dir)
        print(f"  {char_id}: {len(expressions)} sprites")

    # Backgrounds
    bg_dir = base / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    for bg_id, (r, g, b, label) in BACKGROUNDS.items():
        generate_background_placeholder(bg_id, (r, g, b), label, bg_dir)
    print(f"  {len(BACKGROUNDS)} backgrounds")

    total = sum(len(e) for e in CHARACTER_EXPRESSIONS.values()) + len(BACKGROUNDS)
    print(f"\nTotal: {total} assets generated.")


if __name__ == "__main__":
    main()
