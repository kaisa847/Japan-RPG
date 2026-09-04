"""Generate game assets via local Stable Diffusion WebUI (A1111 API).

Requires sd.webui running with --api (default: http://127.0.0.1:7860).

Backgrounds (photorealistic, 1920x1080):
    python generate_assets_sd.py                  # generate all missing backgrounds
    python generate_assets_sd.py --only izakaya   # generate specific background(s)
    python generate_assets_sd.py --force          # regenerate even if file exists

Character sprites (anime, 640x1536, transparent background via rembg):
    python generate_assets_sd.py sprite --list                        # show presets
    python generate_assets_sd.py sprite --expression happy            # engine sprite slot
    python generate_assets_sd.py sprite --expression happy --outfit yukata
    python generate_assets_sd.py sprite --expression excited --gesture waving
    python generate_assets_sd.py sprite --expression neutral --outfit winter --seed 42

Sprites with the standard outfit and no gesture go to the engine slot
(assets/characters/aoi/<expression>.png, --force needed to overwrite).
Everything else goes to assets/characters/aoi/variants/ — the engine
ignores that folder, it is the playground for new outfits and gestures.
"""

import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path

API_BASE = "http://127.0.0.1:7860"
ASSETS_DIR = Path(__file__).parent / "assets"

# --- Backgrounds ---------------------------------------------------------

# Two interchangeable background styles. Sets are generated into
# assets/backgrounds_<style>/ and activated by copying into
# assets/backgrounds/ ("switch-style" subcommand).
BG_STYLES = {
    "photo": {
        "model": "juggernautXL_version6Rundiffusion",
        "style": (
            "photorealistic, professional photography, natural lighting, "
            "high detail, sharp focus, 8k, tokyo japan"
        ),
        "negative": (
            "people, person, human, crowd, anime, cartoon, illustration, "
            "painting, drawing, text, watermark, signature, logo, blurry, "
            "lowres, deformed, distorted, oversaturated"
        ),
    },
    "anime": {
        "model": "novaAnimeXL_ilV120",
        "style": (
            "highly detailed anime background art, visual novel scenery, "
            "beautiful soft lighting, vibrant colors, crisp clean lineart, "
            "scenic illustration, no humans, tokyo japan"
        ),
        "negative": (
            "photo, photorealistic, 3d render, people, person, human, crowd, "
            "1girl, 1boy, text, watermark, signature, logo, blurry, lowres, "
            "deformed, oversaturated"
        ),
    },
}

# background_id -> scene prompt (ids match data/locations.json;
# style/negative appended automatically)
BACKGROUNDS = {
    "apartment": (
        "small japanese studio apartment interior, single bed with plain bedding, "
        "low wooden table, laptop, bookshelf, balcony window with soft afternoon "
        "light, tatami accents, tidy and modest, lived-in"
    ),
    "shimokitazawa_station": (
        "shimokitazawa train station south exit, ticket gates, station "
        "signage, small station plaza, afternoon light"
    ),
    "shimokitazawa_street": (
        "narrow shimokitazawa shopping street, small independent shops, "
        "tangled power lines overhead, colorful storefronts, daytime"
    ),
    "cafe": (
        "cozy cafe interior, small round wooden tables with chairs, espresso "
        "machine on the counter, cake display, large window, hanging plants"
    ),
    "park": (
        "japanese neighborhood park, cherry trees, walking path, benches, "
        "soft spring light"
    ),
    "shrine": (
        "small hillside shinto shrine, red torii gate, stone steps, old "
        "trees, peaceful atmosphere"
    ),
    "konbini": (
        "japanese convenience store interior, bright shelves with snacks "
        "and bento, drink coolers, clean floor, fluorescent light"
    ),
    "ramen_shop": (
        "small ramen restaurant interior, long wooden counter with red stools "
        "facing the open kitchen, steaming pots, bowls and ladles, hanging "
        "noren curtain, handwritten menu strips on the wall, warm evening light"
    ),
    "vintage_shop": (
        "vintage second-hand clothing store interior, clothing racks full of "
        "colorful retro jackets and shirts on hangers, mannequin, hat shelf, "
        "band posters, old wooden floor, warm tungsten lighting"
    ),
    "record_store": (
        "record store interior, wooden crates full of vinyl records with "
        "visible album sleeves, colorful album covers hanging on the wall, "
        "turntable listening station with headphones, cozy cluttered shop"
    ),
    "bookshop": (
        "small cozy japanese bookshop interior, floor-to-ceiling wooden "
        "bookshelves, stacks of books, narrow aisle, warm reading lamps, "
        "quiet atmosphere"
    ),
    "izakaya": (
        "traditional japanese izakaya interior, wooden counter with sake bottles "
        "on shelves, red paper lanterns, handwritten menu strips on walls, "
        "warm inviting evening light"
    ),
    "karaoke": (
        "japanese karaoke box room interior, l-shaped sofa, low table with "
        "microphones and remote, large tv screen on wall, colorful mood "
        "lighting, slightly dim"
    ),
    "temple": (
        "japanese buddhist temple grounds, wooden main hall with curved roof, "
        "large bronze incense burner with smoke, stone path, old trees, "
        "peaceful late afternoon light"
    ),
    "rooftop": (
        "tokyo apartment building rooftop at dusk, safety railing, potted "
        "plants, two folding chairs, city skyline with lit windows in the "
        "distance, orange and purple sky"
    ),
    "live_house": (
        "small underground live music venue in shimokitazawa, low stage with "
        "amps and drum kit, band posters covering dark walls, stage lights, "
        "standing area, intimate club atmosphere"
    ),
    "laundromat": (
        "small japanese coin laundromat interior at night, row of washing "
        "machines and dryers, fluorescent lighting, plastic chairs, "
        "detergent vending machine, clean tiled floor"
    ),
    "bath_house": (
        "traditional japanese sento bath house entrance hall, wooden shoe "
        "lockers, noren curtain, tiled floor, retro signage, warm "
        "nostalgic lighting"
    ),
}

# --- Character sprites (Baukasten) ---------------------------------------
# Reference: data/characters/aoi.visual.md. Base prompt and negative match
# the generation that produced the shipped sprites (seed 3266706159).

SPRITE_MODEL = "animaPencilXL_v100"
SPRITE_SIZE = (640, 1536)
SPRITE_SEED = 3266706159

# Identity LoRA (trained on the shipped Aoi sprites). Used automatically if
# the file exists in the WebUI Lora folder; disable with --no-lora.
SPRITE_LORA = "aoi_identity_v1"
SPRITE_LORA_WEIGHT = 0.8
SPRITE_LORA_TRIGGER = "aoihayashi"
LORA_DIR = Path(
    r"C:\Users\kaisa\AppData\Local\sd.webui\webui\models\Lora"
)

CHARACTERS = {
    "aoi": {
        "base": (
            "1girl, solo, 22 years old, brown shoulder-length hair with messy "
            "bangs, brown eyes, round face, gentle features, fair skin with "
            "warm undertone, 162cm tall, slender athletic build"
        ),
        "outfits": {
            "standard": (
                "wearing oversized cream knit sweater, light blue mom jeans, "
                "white sneakers"
            ),
            "casual2": (
                "wearing striped long-sleeve shirt, plaid mini skirt, "
                "white canvas sneakers, small hoop earrings"
            ),
            "yukata": (
                "wearing light blue yukata with pink floral pattern, obi sash, "
                "geta sandals, small flower hair ornament"
            ),
            "winter": (
                "wearing beige wool coat over cream sweater, knit scarf, "
                "dark jeans, ankle boots"
            ),
            "rain": (
                "wearing yellow raincoat over casual clothes, rubber boots"
            ),
            "pajama": (
                "wearing loose oversized pastel pink pajama shirt and long pajama "
                "pants, comfortable sleepwear, barefoot, slightly messy hair"
            ),
        },
        "expressions": {
            "neutral": "slight smile, relaxed expression, standard pose",
            "happy": "wide smile, dimples visible, eyes slightly closed, cheerful",
            "excited": "sparkling eyes, open mouth, energetic",
            "curious": "head tilted, large eyes, finger on chin, inquisitive",
            "talking": "half-open mouth, gesturing, conversational",
            "laughing": "eyes closed, wide open mouth, head tilted back",
            "surprised": "wide eyes, slightly open mouth, raised eyebrows",
            "thinking": "looking up-left, hand on cheek, contemplative",
            "embarrassed": "slight blush, looking aside, nervous smile",
            "determined": "focused gaze, closed mouth, fist clenched",
            "worried": "furrowed brows, concerned look",
            "sleepy": "half-closed eyes, yawning mouth",
            "angry": "angry expression, furrowed brows, pout, puffed cheeks",
            "disgusted": "disgusted expression, grimace, narrowed eyes",
            "shocked": "shocked expression, wide eyes, pale, open mouth",
            "ahegao": "ahegao expression, rolling eyes, blushing, open mouth",
        },
        "negative": (
            "distorted, distorted face, distorted eyes, distorted hands, "
            "bare shoulders, deformed, midget, mutant, child, children, "
            "crouching, necklace"
        ),
    },
}

GESTURES = {
    "waving": "waving at viewer, one hand raised",
    "peace": "peace sign with one hand",
    "pointing": "pointing at viewer",
    "arms-crossed": "arms crossed",
    "hands-behind-back": "hands behind back, leaning forward slightly",
    "phone": "holding smartphone in one hand",
    "coffee": "holding paper coffee cup",
}

SPRITE_STYLE = (
    "anime style, soft shading, warm color palette, clean lineart, "
    "visual novel character sprite, white background, full body shot, "
    "standing pose, high quality, detailed, sharp focus"
)


# --- API helpers ---------------------------------------------------------


def api_call(path: str, payload: dict | None = None, timeout: int = 600):
    url = f"{API_BASE}{path}"
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def require_api() -> bool:
    try:
        api_call("/sdapi/v1/options")
        return True
    except Exception:
        print(f"ERROR: SD WebUI API not reachable at {API_BASE}.")
        print("Start it with: sd.webui\\webui\\webui.bat --api")
        return False


def pick_upscaler() -> str:
    try:
        names = [u["name"] for u in api_call("/sdapi/v1/upscalers")]
    except Exception:
        return "Lanczos"
    for preferred in ("R-ESRGAN 4x+", "ESRGAN_4x", "SwinIR 4x", "Lanczos"):
        if preferred in names:
            return preferred
    return "Lanczos"


# --- Backgrounds mode ----------------------------------------------------


def generate_background(prompt: str, upscaler: str, style: dict) -> bytes:
    payload = {
        "prompt": f"{prompt}, {style['style']}",
        "negative_prompt": style["negative"],
        "steps": 30,
        "sampler_name": "DPM++ 2M",
        "scheduler": "karras",
        "cfg_scale": 6,
        "width": 1344,
        "height": 768,
        "enable_hr": True,
        "hr_upscaler": upscaler,
        "hr_resize_x": 1920,
        "hr_resize_y": 1080,
        "hr_second_pass_steps": 12,
        "denoising_strength": 0.35,
        "override_settings": {"sd_model_checkpoint": style["model"]},
        "override_settings_restore_afterwards": False,
    }
    result = api_call("/sdapi/v1/txt2img", payload)
    return base64.b64decode(result["images"][0])


def switch_style_main(argv: list[str]) -> int:
    import shutil

    parser = argparse.ArgumentParser(prog="generate_assets_sd.py switch-style")
    parser.add_argument("style", choices=sorted(BG_STYLES))
    args = parser.parse_args(argv)

    src_dir = ASSETS_DIR / f"backgrounds_{args.style}"
    dst_dir = ASSETS_DIR / "backgrounds"
    if not src_dir.exists():
        print(f"ERROR: {src_dir} does not exist")
        return 1
    n = 0
    for f in sorted(src_dir.glob("*.png")):
        shutil.copy(f, dst_dir / f.name)
        n += 1
    print(f"activated style '{args.style}' ({n} backgrounds)")
    return 0


def backgrounds_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="generate_assets_sd.py")
    parser.add_argument("--only", nargs="*", help="generate only these background ids")
    parser.add_argument("--style", default="anime", choices=sorted(BG_STYLES))
    parser.add_argument("--activate", action="store_true",
                        help="also copy generated files into assets/backgrounds/")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args(argv)

    if not require_api():
        return 1

    style = BG_STYLES[args.style]

    targets = dict(BACKGROUNDS)
    if args.only:
        unknown = set(args.only) - set(targets)
        if unknown:
            print(f"Unknown background ids: {', '.join(sorted(unknown))}")
            return 1
        targets = {k: v for k, v in targets.items() if k in args.only}

    upscaler = pick_upscaler()
    print(f"Style '{args.style}', model {style['model']}, upscaler: {upscaler}")

    bg_dir = ASSETS_DIR / f"backgrounds_{args.style}"
    active_dir = ASSETS_DIR / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    for bg_id, prompt in targets.items():
        out_path = bg_dir / f"{bg_id}.png"
        if out_path.exists() and not args.force:
            print(f"skip   {bg_id} (exists)")
            continue
        print(f"gen    {bg_id} ...", flush=True)
        png = generate_background(prompt, upscaler, style)
        out_path.write_bytes(png)
        if args.activate:
            (active_dir / f"{bg_id}.png").write_bytes(png)
        print(f"saved  {out_path} ({len(png) // 1024} KB)")

    return 0


# --- Sprite mode ---------------------------------------------------------


def remove_background(png: bytes) -> bytes:
    """Cut out the character via rembg (anime-tuned model) -> RGBA PNG."""
    from rembg import new_session, remove

    session = new_session("isnet-anime")
    return remove(png, session=session)


def generate_sprite(char: dict, prompt_parts: list[str], seed: int, steps: int) -> bytes:
    payload = {
        "prompt": ",\n".join(prompt_parts),
        "negative_prompt": char["negative"],
        "steps": steps,
        "sampler_name": "DPM++ 2M",
        "scheduler": "karras",
        "cfg_scale": 7,
        "width": SPRITE_SIZE[0],
        "height": SPRITE_SIZE[1],
        "seed": seed,
        "override_settings": {"sd_model_checkpoint": SPRITE_MODEL},
        "override_settings_restore_afterwards": False,
    }
    result = api_call("/sdapi/v1/txt2img", payload)
    return base64.b64decode(result["images"][0])


def sprite_out_path(char_id: str, char: dict, expression: str, outfit: str,
                    gesture: str | None, out_name: str | None) -> Path:
    """Engine slots: standard outfit -> root, known outfit -> subfolder.
    Everything else (gestures, free text, custom name) -> variants/."""
    char_dir = ASSETS_DIR / "characters" / char_id
    known_expr = expression in char["expressions"]
    known_outfit = outfit in char["outfits"]
    if not out_name and not gesture and known_expr and known_outfit:
        if outfit == "standard":
            return char_dir / f"{expression}.png"
        return char_dir / outfit / f"{expression}.png"
    name = out_name
    if not name:
        name = f"{outfit}_{expression}".replace(" ", "-")
        if gesture:
            name += f"_{gesture}".replace(" ", "-")
    return char_dir / "variants" / f"{name}.png"


def sprite_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="generate_assets_sd.py sprite")
    parser.add_argument("--char", default="aoi", choices=sorted(CHARACTERS))
    parser.add_argument("--expression", help="preset name or free-text expression tags")
    parser.add_argument("--all-expressions", action="store_true",
                        help="generate every preset expression (e.g. a full outfit set)")
    parser.add_argument("--outfit", default="standard",
                        help="preset name or free-text outfit tags")
    parser.add_argument("--gesture", help="preset name or free-text gesture tags")
    parser.add_argument("--seed", type=int, default=SPRITE_SEED,
                        help=f"generation seed (default {SPRITE_SEED} = shipped Aoi sprites)")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--out", help="output name without extension")
    parser.add_argument("--no-lora", action="store_true",
                        help="generate without the identity LoRA")
    parser.add_argument("--lora-weight", type=float, default=SPRITE_LORA_WEIGHT)
    parser.add_argument("--keep-bg", action="store_true",
                        help="skip background removal (debug)")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--list", action="store_true", help="show available presets")
    args = parser.parse_args(argv)

    char = CHARACTERS[args.char]

    if args.list:
        print(f"Character: {args.char}")
        print("Expressions:", ", ".join(char["expressions"]))
        print("Outfits:    ", ", ".join(char["outfits"]))
        print("Gestures:   ", ", ".join(GESTURES))
        print("(free text is accepted for --expression/--outfit/--gesture too)")
        lora_file = LORA_DIR / f"{SPRITE_LORA}.safetensors"
        print(f"Identity LoRA: {'available' if lora_file.exists() else 'NOT FOUND'}"
              f" ({lora_file})")
        return 0

    if args.all_expressions:
        expressions = list(char["expressions"])
    elif args.expression:
        expressions = [args.expression]
    else:
        print("ERROR: --expression or --all-expressions is required (or use --list)")
        return 1

    lora_file = LORA_DIR / f"{SPRITE_LORA}.safetensors"
    use_lora = not args.no_lora and lora_file.exists()
    if use_lora:
        print(f"Using identity LoRA {SPRITE_LORA} (weight {args.lora_weight})")

    if not require_api():
        return 1

    gesture_tags = GESTURES.get(args.gesture, args.gesture) if args.gesture else None
    outfit_tags = char["outfits"].get(args.outfit, args.outfit)

    for expression in expressions:
        expression_tags = char["expressions"].get(expression, expression)

        base = char["base"]
        if use_lora:
            base = f"<lora:{SPRITE_LORA}:{args.lora_weight}> {SPRITE_LORA_TRIGGER}, {base}"

        prompt_parts = [base, outfit_tags, expression_tags]
        if gesture_tags:
            prompt_parts.append(gesture_tags)
        prompt_parts.append(SPRITE_STYLE)

        out_path = sprite_out_path(
            args.char, char, expression, args.outfit, args.gesture, args.out
        )
        if out_path.exists() and not args.force:
            print(f"skip   {out_path.name} (exists, use --force)")
            continue

        print(f"gen    {out_path} (seed {args.seed})", flush=True)
        png = generate_sprite(char, prompt_parts, args.seed, args.steps)
        if not args.keep_bg:
            print("cut    removing background (rembg isnet-anime) ...", flush=True)
            png = remove_background(png)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(png)
        print(f"saved  {out_path} ({len(png) // 1024} KB)")
    return 0


# --- Animation patches (blink / mouth flap) ------------------------------
# For each expression sprite, inpaint the eye band (closed eyes) and the
# mouth band (opposite mouth state) via img2img, then store the changed
# regions as small RGBA patches that the frontend overlays on the sprite.

CASCADE_PATH = Path(__file__).parent / "tools" / "lbpcascade_animeface.xml"

# Band geometry as fractions of the detected face box
EYE_BAND = (0.02, 0.26, 0.98, 0.55)    # x0, y0, x1, y1
MOUTH_BAND = (0.22, 0.56, 0.78, 0.85)
PATCH_MARGIN = 10                       # px of unchanged context around the band

# Expressions whose base sprite already shows an open mouth get a
# closed-mouth patch; all others get an open-mouth patch.
OPEN_MOUTH_BASES = {"excited", "talking", "laughing", "surprised", "sleepy",
                    "shocked", "ahegao"}

EYES_PROMPT = "closed eyes, eyelashes, peaceful"
MOUTH_OPEN_PROMPT = "open mouth, talking"
MOUTH_CLOSED_PROMPT = "closed mouth, slight smile"


def detect_face(rgb_image) -> tuple[int, int, int, int] | None:
    import cv2
    import numpy as np

    cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
    gray = cv2.cvtColor(np.array(rgb_image), cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.05, minNeighbors=5, minSize=(80, 80)
    )
    if len(faces) == 0:
        return None
    # Largest detection wins
    return tuple(max(faces, key=lambda f: f[2] * f[3]))


def band_rect(face, band, size) -> tuple[int, int, int, int]:
    fx, fy, fw, fh = face
    x0 = max(0, fx + int(band[0] * fw))
    y0 = max(0, fy + int(band[1] * fh))
    x1 = min(size[0], fx + int(band[2] * fw))
    y1 = min(size[1], fy + int(band[3] * fh))
    return x0, y0, x1, y1


def inpaint_region(char: dict, rgb_image, rect, prompt: str, seed: int,
                   use_lora: bool, lora_weight: float):
    """Inpaint rect on the sprite via img2img, return full-size RGB result."""
    import io
    from PIL import Image

    buf = io.BytesIO()
    rgb_image.save(buf, format="PNG")
    init_b64 = base64.b64encode(buf.getvalue()).decode()

    mask = Image.new("L", rgb_image.size, 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).rectangle(rect, fill=255)
    mbuf = io.BytesIO()
    mask.save(mbuf, format="PNG")
    mask_b64 = base64.b64encode(mbuf.getvalue()).decode()

    full_prompt = f"{prompt}, anime style, clean lineart"
    if use_lora:
        full_prompt = (
            f"<lora:{SPRITE_LORA}:{lora_weight}> {SPRITE_LORA_TRIGGER}, {full_prompt}"
        )

    payload = {
        "init_images": [init_b64],
        "mask": mask_b64,
        "prompt": full_prompt,
        "negative_prompt": char["negative"],
        "denoising_strength": 0.75,
        "mask_blur": 8,
        "inpainting_fill": 1,
        "inpaint_full_res": True,
        "inpaint_full_res_padding": 64,
        "inpainting_mask_invert": 0,
        "steps": 24,
        "sampler_name": "DPM++ 2M",
        "scheduler": "karras",
        "cfg_scale": 7,
        "width": rgb_image.size[0],
        "height": rgb_image.size[1],
        "seed": seed,
        "override_settings": {"sd_model_checkpoint": SPRITE_MODEL},
        "override_settings_restore_afterwards": False,
    }
    result = api_call("/sdapi/v1/img2img", payload)
    return Image.open(io.BytesIO(base64.b64decode(result["images"][0]))).convert("RGB")


def extract_patch(base_rgba, inpainted_rgb, rect, size):
    """Crop rect+margin; RGB from inpaint, alpha from the base sprite."""
    from PIL import Image

    x0 = max(0, rect[0] - PATCH_MARGIN)
    y0 = max(0, rect[1] - PATCH_MARGIN)
    x1 = min(size[0], rect[2] + PATCH_MARGIN)
    y1 = min(size[1], rect[3] + PATCH_MARGIN)
    patch = inpainted_rgb.crop((x0, y0, x1, y1)).convert("RGBA")
    alpha = base_rgba.crop((x0, y0, x1, y1)).getchannel("A")
    patch.putalpha(alpha)
    geometry = {
        "x": round(x0 / size[0], 4),
        "y": round(y0 / size[1], 4),
        "w": round((x1 - x0) / size[0], 4),
        "h": round((y1 - y0) / size[1], 4),
    }
    return patch, geometry


def anim_main(argv: list[str]) -> int:
    from PIL import Image

    parser = argparse.ArgumentParser(prog="generate_assets_sd.py anim")
    parser.add_argument("--char", default="aoi", choices=sorted(CHARACTERS))
    parser.add_argument("--outfit", default="standard")
    parser.add_argument("--expressions", nargs="*",
                        help="default: all preset expressions")
    parser.add_argument("--seed", type=int, default=SPRITE_SEED)
    parser.add_argument("--no-lora", action="store_true")
    parser.add_argument("--lora-weight", type=float, default=SPRITE_LORA_WEIGHT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    char = CHARACTERS[args.char]
    expressions = args.expressions or list(char["expressions"])

    char_dir = ASSETS_DIR / "characters" / args.char
    anim_dir = char_dir / "anim"
    anim_json_path = anim_dir / "anim.json"
    anim_data: dict = {}
    if anim_json_path.exists():
        anim_data = json.loads(anim_json_path.read_text(encoding="utf-8"))

    lora_file = LORA_DIR / f"{SPRITE_LORA}.safetensors"
    use_lora = not args.no_lora and lora_file.exists()

    if not require_api():
        return 1

    for expression in expressions:
        sprite_path = (
            char_dir / f"{expression}.png" if args.outfit == "standard"
            else char_dir / args.outfit / f"{expression}.png"
        )
        if not sprite_path.exists():
            print(f"skip   {args.outfit}/{expression} (no base sprite)")
            continue
        existing = anim_data.get(args.outfit, {}).get(expression)
        if existing and not args.force:
            print(f"skip   {args.outfit}/{expression} (already animated)")
            continue

        base_rgba = Image.open(sprite_path).convert("RGBA")
        rgb = Image.new("RGB", base_rgba.size, (255, 255, 255))
        rgb.paste(base_rgba, (0, 0), base_rgba)

        face = detect_face(rgb)
        if face is None:
            print(f"skip   {args.outfit}/{expression} (no face detected)")
            continue

        out_sub = anim_dir / args.outfit
        out_sub.mkdir(parents=True, exist_ok=True)
        entry = {}

        # Blink patch (closed eyes)
        rect = band_rect(face, EYE_BAND, rgb.size)
        print(f"gen    {args.outfit}/{expression} eyes_closed ...", flush=True)
        inpainted = inpaint_region(char, rgb, rect, EYES_PROMPT, args.seed,
                                   use_lora, args.lora_weight)
        patch, geo = extract_patch(base_rgba, inpainted, rect, rgb.size)
        fname = f"{args.outfit}/{expression}_eyes_closed.png"
        patch.save(anim_dir / fname)
        entry["eyes_closed"] = {"file": fname, **geo}

        # Mouth patch (opposite of the base state)
        rect = band_rect(face, MOUTH_BAND, rgb.size)
        mouth_prompt = (
            MOUTH_CLOSED_PROMPT if expression in OPEN_MOUTH_BASES
            else MOUTH_OPEN_PROMPT
        )
        print(f"gen    {args.outfit}/{expression} mouth ...", flush=True)
        inpainted = inpaint_region(char, rgb, rect, mouth_prompt, args.seed,
                                   use_lora, args.lora_weight)
        patch, geo = extract_patch(base_rgba, inpainted, rect, rgb.size)
        fname = f"{args.outfit}/{expression}_mouth.png"
        patch.save(anim_dir / fname)
        entry["mouth"] = {"file": fname, **geo}

        anim_data.setdefault(args.outfit, {})[expression] = entry
        anim_json_path.parent.mkdir(parents=True, exist_ok=True)
        anim_json_path.write_text(
            json.dumps(anim_data, indent=2), encoding="utf-8"
        )
        print(f"saved  {args.outfit}/{expression} patches + anim.json")

    return 0


# --- Layered sprites: pose bodies + face patches (docs/ASSET_PIPELINE.md) --

POSES_DIR = Path(__file__).parent / "tools" / "poses"
CN_MODEL = "controlnet-openpose-sdxl-xinsir"

# Face anchor shared by all poses (skeletons pin the head): center of the
# face patch relative to the 640x1536 body, patch width as body-width share.
FACE_ANCHOR = {"x": 0.47, "y": 0.131, "w": 0.375}

POSE_PROMPTS = {
    "stand": "standing relaxed, arms at sides",
    "wave": "waving cheerfully, arm raised high, open palm next to head",
    "arms_crossed": "arms crossed in front of chest",
    "hands_clasped": "hands clasped together in front of body, shy",
    "pointing": "pointing to the side with outstretched right arm",
    "phone": "holding a smartphone against her ear, talking on the phone",
}

BLINK_PROMPT = "closed eyes, gentle eyelashes, relaxed face"

# Faces whose eyes are already (half-)closed by design — blinking on top
# of them looks wrong, the engine skips it via manifest.no_blink_faces.
CLOSED_EYE_FACES = {"happy", "laughing", "sleepy", "blink"}


def controlnet_unit(skeleton_png: Path) -> dict:
    image_b64 = base64.b64encode(skeleton_png.read_bytes()).decode()
    return {
        "enabled": True,
        "image": image_b64,
        "module": "none",
        "model": CN_MODEL,
        "weight": 0.95,
        "resize_mode": "Just Resize",
        "guidance_start": 0.0,
        "guidance_end": 1.0,
        "control_mode": "Balanced",
    }


def generate_pose_body(char: dict, pose: str, outfit_tags: str, seed: int,
                       use_lora: bool, lora_weight: float) -> bytes:
    base = char["base"]
    if use_lora:
        base = f"<lora:{SPRITE_LORA}:{lora_weight}> {SPRITE_LORA_TRIGGER}, {base}"
    prompt_parts = [
        base, outfit_tags,
        "neutral expression, slight smile, looking at viewer",
        POSE_PROMPTS.get(pose, pose),
        SPRITE_STYLE,
    ]
    payload = {
        "prompt": ",\n".join(prompt_parts),
        "negative_prompt": char["negative"],
        "steps": 26,
        "sampler_name": "DPM++ 2M",
        "scheduler": "karras",
        "cfg_scale": 7,
        "width": SPRITE_SIZE[0],
        "height": SPRITE_SIZE[1],
        "seed": seed,
        "override_settings": {"sd_model_checkpoint": SPRITE_MODEL},
        "override_settings_restore_afterwards": False,
        "alwayson_scripts": {
            "controlnet": {"args": [controlnet_unit(POSES_DIR / f"{pose}.png")]},
        },
    }
    result = api_call("/sdapi/v1/txt2img", payload)
    return base64.b64decode(result["images"][0])


def pose_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="generate_assets_sd.py pose")
    parser.add_argument("--char", default="aoi", choices=sorted(CHARACTERS))
    parser.add_argument("--outfit", default="standard")
    parser.add_argument("--poses", nargs="*", help="default: all 6 poses")
    parser.add_argument("--seed", type=int, default=SPRITE_SEED)
    parser.add_argument("--no-lora", action="store_true")
    parser.add_argument("--lora-weight", type=float, default=SPRITE_LORA_WEIGHT)
    parser.add_argument("--keep-bg", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    char = CHARACTERS[args.char]
    poses = args.poses or list(POSE_PROMPTS)
    outfit_tags = char["outfits"].get(args.outfit, args.outfit)

    lora_file = LORA_DIR / f"{SPRITE_LORA}.safetensors"
    use_lora = not args.no_lora and lora_file.exists()

    if not require_api():
        return 1

    char_dir = ASSETS_DIR / "characters" / args.char
    for pose in poses:
        if not (POSES_DIR / f"{pose}.png").exists():
            print(f"skip   {pose} (no skeleton — run tools/openpose_poses.py)")
            continue
        out_path = (
            char_dir / "poses" / f"{pose}.png" if args.outfit == "standard"
            else char_dir / "poses" / args.outfit / f"{pose}.png"
        )
        if out_path.exists() and not args.force:
            print(f"skip   {pose} (exists)")
            continue
        print(f"gen    pose {args.outfit}/{pose} ...", flush=True)
        png = generate_pose_body(char, pose, outfit_tags, args.seed,
                                 use_lora, args.lora_weight)
        if not args.keep_bg:
            png = remove_background(png)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(png)
        print(f"saved  {out_path} ({len(png) // 1024} KB)")
    return 0


def face_patch_rect(size) -> tuple[int, int, int, int]:
    half = int(FACE_ANCHOR["w"] * size[0] / 2)
    cx = int(FACE_ANCHOR["x"] * size[0])
    cy = int(FACE_ANCHOR["y"] * size[1])
    return (cx - half, cy - half, cx + half, cy + half)


def faces_main(argv: list[str]) -> int:
    import io
    from PIL import Image

    parser = argparse.ArgumentParser(prog="generate_assets_sd.py faces")
    parser.add_argument("--char", default="aoi", choices=sorted(CHARACTERS))
    parser.add_argument("--expressions", nargs="*",
                        help="default: all presets + blink")
    parser.add_argument("--seed", type=int, default=SPRITE_SEED)
    parser.add_argument("--no-lora", action="store_true")
    parser.add_argument("--lora-weight", type=float, default=SPRITE_LORA_WEIGHT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    char = CHARACTERS[args.char]
    expressions = args.expressions or (list(char["expressions"]) + ["blink"])

    char_dir = ASSETS_DIR / "characters" / args.char
    body_path = char_dir / "poses" / "stand.png"
    if not body_path.exists():
        print("ERROR: poses/stand.png missing — generate pose bodies first")
        return 1

    lora_file = LORA_DIR / f"{SPRITE_LORA}.safetensors"
    use_lora = not args.no_lora and lora_file.exists()

    if not require_api():
        return 1

    body_rgba = Image.open(body_path).convert("RGBA")
    rgb = Image.new("RGB", body_rgba.size, (255, 255, 255))
    rgb.paste(body_rgba, (0, 0), body_rgba)
    rect = face_patch_rect(rgb.size)
    # inpaint mask slightly inside the patch so crop edges stay untouched
    inset = 14
    mask_rect = (rect[0] + inset, rect[1] + inset, rect[2] - inset, rect[3] - inset)

    # mouth band inside the face square, for the _talk variants
    fw = rect[2] - rect[0]
    fh = rect[3] - rect[1]
    mouth_rect = (
        rect[0] + int(0.28 * fw), rect[1] + int(0.62 * fh),
        rect[2] - int(0.28 * fw), rect[3] - int(0.06 * fh),
    )

    faces_dir = char_dir / "faces"
    faces_dir.mkdir(parents=True, exist_ok=True)
    for expr in expressions:
        out_path = faces_dir / f"{expr}.png"
        talk_path = faces_dir / f"{expr}_talk.png"
        tags = BLINK_PROMPT if expr == "blink" else char["expressions"].get(expr, expr)

        inpainted = None
        if out_path.exists() and not args.force:
            print(f"skip   {expr} (exists)")
        else:
            print(f"gen    face {expr} ...", flush=True)
            inpainted = inpaint_region(char, rgb, mask_rect, tags, args.seed,
                                       use_lora, args.lora_weight)
            patch = inpainted.crop(rect).convert("RGBA")
            patch.putalpha(body_rgba.crop(rect).getchannel("A"))
            patch.save(out_path)
            print(f"saved  {out_path}")

        # Talk variant: opposite mouth state, eyes untouched (second
        # inpaint of just the mouth band on the expression result)
        if expr == "blink":
            continue
        if talk_path.exists() and not args.force:
            continue
        if inpainted is None:
            # rebuild the expression full-image by pasting the existing
            # patch onto the body so the talk inpaint matches it
            inpainted = rgb.copy()
            existing = Image.open(out_path).convert("RGBA")
            inpainted.paste(existing.convert("RGB"), (rect[0], rect[1]),
                            existing)
        mouth_tags = (
            MOUTH_CLOSED_PROMPT if expr in OPEN_MOUTH_BASES else MOUTH_OPEN_PROMPT
        )
        print(f"gen    face {expr}_talk ...", flush=True)
        talk_full = inpaint_region(char, inpainted, mouth_rect, mouth_tags,
                                   args.seed, use_lora, args.lora_weight)
        patch = talk_full.crop(rect).convert("RGBA")
        patch.putalpha(body_rgba.crop(rect).getchannel("A"))
        patch.save(talk_path)
        print(f"saved  {talk_path}")

    write_manifest(args.char, char)
    return 0


def write_manifest(char_id: str, char: dict) -> None:
    """Build manifest.json from the files actually on disk."""
    char_dir = ASSETS_DIR / "characters" / char_id
    poses_dir = char_dir / "poses"
    faces_dir = char_dir / "faces"

    poses = {}
    for f in sorted(poses_dir.glob("*.png")) if poses_dir.exists() else []:
        poses[f.stem] = {"body": f"poses/{f.name}", "anchor": dict(FACE_ANCHOR)}

    outfits = {}
    if poses_dir.exists():
        for sub in sorted(p for p in poses_dir.iterdir() if p.is_dir()):
            entry = {}
            for f in sorted(sub.glob("*.png")):
                entry[f.stem] = {
                    "body": f"poses/{sub.name}/{f.name}",
                    "anchor": dict(FACE_ANCHOR),
                }
            if entry:
                outfits[sub.name] = {"poses": entry}

    all_pngs = (
        sorted(f.stem for f in faces_dir.glob("*.png"))
        if faces_dir.exists() else []
    )
    # blink stays in the faces list (the manifest validator requires
    # blink_face to be a listed face); _talk files are variants, not faces
    faces = [f for f in all_pngs if not f.endswith("_talk")]
    talk_faces = sorted(
        f[:-len("_talk")] for f in all_pngs
        if f.endswith("_talk") and f[:-len("_talk")] in faces
    )

    if not poses or not faces:
        print("manifest: skipped (need poses and faces)")
        return

    manifest = {
        "version": 1,
        "default_pose": "stand",
        "default_face": "neutral",
        "blink_face": "blink" if (faces_dir / "blink.png").exists() else None,
        "poses": poses,
        "faces": faces,
    }
    if talk_faces:
        manifest["talk_faces"] = talk_faces
    no_blink = sorted(f for f in faces if f in CLOSED_EYE_FACES)
    if no_blink:
        manifest["no_blink_faces"] = no_blink
    if outfits:
        manifest["outfits"] = outfits
    if manifest["blink_face"] is None:
        del manifest["blink_face"]
    path = char_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote  {path} ({len(poses)} poses, {len(faces)} faces, "
          f"{len(talk_faces)} talk variants, {len(outfits)} outfits)")


# --- Dispatch ------------------------------------------------------------


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "sprite":
        return sprite_main(argv[1:])
    if argv and argv[0] == "anim":
        return anim_main(argv[1:])
    if argv and argv[0] == "switch-style":
        return switch_style_main(argv[1:])
    if argv and argv[0] == "pose":
        return pose_main(argv[1:])
    if argv and argv[0] == "faces":
        return faces_main(argv[1:])
    return backgrounds_main(argv)


if __name__ == "__main__":
    sys.exit(main())
