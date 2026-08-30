"""Starter-Gerüst für die Asset-Produktion per A1111 Stable-Diffusion-API.

ACHTUNG: UNGETESTET — dieses Skript wurde ohne laufende SD-Instanz
geschrieben. Es ist ein Ausgangspunkt für die lokale Asset-Session
(siehe docs/HANDOVER_ASSET_SESSION.md), kein fertiges Werkzeug.
Aufrufe gegen die echte API prüfen und bei Bedarf anpassen.

Abhängigkeiten: pip install requests pillow rembg onnxruntime

Bausteine:
  SDClient          — txt2img / img2img-Inpainting gegen A1111
  cutout()          — Freistellen via rembg
  face_mask()       — Inpainting-Maske aus dem Manifest-Anker
  extract_patch()   — Gesichts-Patch aus einem Inpaint-Ergebnis schneiden
  write_manifest()  — manifest.json im Engine-Format schreiben
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import requests
from PIL import Image

A1111_URL = "http://127.0.0.1:7860"

# Zielmaße laut docs/ASSET_PIPELINE.md
BODY_SIZE = (400, 800)        # finale Ablagegröße
GEN_SIZE = (800, 1600)        # Generierungsgröße (wird runterskaliert)
BG_SIZE = (1920, 1080)

POSES = ["stand", "wave", "arms_crossed", "hands_clasped", "pointing", "phone"]
FACES = [
    "neutral", "happy", "excited", "curious", "talking", "laughing",
    "surprised", "thinking", "embarrassed", "determined", "worried",
    "sleepy", "angry", "disgusted", "shocked", "ahegao", "blink",
]


def _b64_to_image(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data)))


def _image_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class SDClient:
    def __init__(self, base_url: str = A1111_URL, timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, endpoint: str, payload: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}{endpoint}", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def check(self) -> list[str]:
        """Return available model titles (also serves as a health check)."""
        resp = requests.get(f"{self.base_url}/sdapi/v1/sd-models", timeout=30)
        resp.raise_for_status()
        return [m["title"] for m in resp.json()]

    def txt2img(
        self,
        prompt: str,
        negative: str = "",
        seed: int = -1,
        size: tuple[int, int] = GEN_SIZE,
        steps: int = 28,
        cfg: float = 6.5,
        controlnet_units: list[dict] | None = None,
    ) -> Image.Image:
        payload = {
            "prompt": prompt,
            "negative_prompt": negative,
            "seed": seed,
            "width": size[0],
            "height": size[1],
            "steps": steps,
            "cfg_scale": cfg,
            "sampler_name": "DPM++ 2M Karras",
        }
        if controlnet_units:
            payload["alwayson_scripts"] = {
                "controlnet": {"args": controlnet_units}
            }
        result = self._post("/sdapi/v1/txt2img", payload)
        return _b64_to_image(result["images"][0])

    def inpaint(
        self,
        image: Image.Image,
        mask: Image.Image,
        prompt: str,
        negative: str = "",
        seed: int = -1,
        denoise: float = 0.6,
        steps: int = 28,
    ) -> Image.Image:
        """Inpaint only the masked region ('only masked' mode)."""
        payload = {
            "init_images": [_image_to_b64(image)],
            "mask": _image_to_b64(mask),
            "prompt": prompt,
            "negative_prompt": negative,
            "seed": seed,
            "denoising_strength": denoise,
            "steps": steps,
            "width": image.width,
            "height": image.height,
            "inpainting_fill": 1,        # original content
            "inpaint_full_res": True,    # only masked
            "inpaint_full_res_padding": 32,
            "sampler_name": "DPM++ 2M Karras",
        }
        result = self._post("/sdapi/v1/img2img", payload)
        return _b64_to_image(result["images"][0])


def openpose_unit(pose_image: Image.Image, weight: float = 1.0) -> dict:
    """ControlNet-Unit für OpenPose (Feldnamen ggf. an Version anpassen)."""
    return {
        "input_image": _image_to_b64(pose_image),
        "module": "none",                 # Bild IST bereits ein Skelett
        "model": "control_v11p_sd15_openpose",  # an installiertes Modell anpassen!
        "weight": weight,
    }


def cutout(img: Image.Image) -> Image.Image:
    """Hintergrund entfernen (rembg)."""
    from rembg import remove
    return remove(img)


def face_mask(body_size: tuple[int, int], anchor: dict, pad: float = 0.1) -> Image.Image:
    """Weiße Inpainting-Maske über der Anker-Region (mit etwas Rand)."""
    w, h = body_size
    mask = Image.new("L", (w, h), 0)
    from PIL import ImageDraw
    d = ImageDraw.Draw(mask)
    half = anchor["w"] * (1 + pad) / 2
    cx, cy = anchor["x"] * w, anchor["y"] * h
    box_w = half * w
    d.ellipse([cx - box_w, cy - box_w, cx + box_w, cy + box_w], fill=255)
    return mask


def extract_patch(
    inpainted_body: Image.Image, anchor: dict
) -> Image.Image:
    """Quadratischen Gesichts-Patch am Anker ausschneiden."""
    w, h = inpainted_body.size
    size = int(anchor["w"] * w)
    cx, cy = int(anchor["x"] * w), int(anchor["y"] * h)
    box = (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2)
    return inpainted_body.crop(box)


def write_manifest(
    char_dir: Path,
    anchors: dict[str, dict],
    faces: list[str] = FACES,
    default_pose: str = "stand",
) -> None:
    manifest = {
        "version": 1,
        "default_pose": default_pose,
        "default_face": "neutral",
        "blink_face": "blink",
        "poses": {
            pose: {"body": f"poses/{pose}.png", "anchor": anchor}
            for pose, anchor in anchors.items()
        },
        "faces": faces,
    }
    (char_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    client = SDClient()
    print("Verfügbare Modelle:")
    for title in client.check():
        print(" -", title)
