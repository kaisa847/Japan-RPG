"""THA3 live animation service for Japanese Life: Tokyo Stories.

Animates the Aoi sprite in real time (blinking, breathing, head sway,
lip flap, expression morphs) using Talking Head Anime 3 and streams the
frames as a multipart PNG stream (with alpha) that the VN frontend can
show directly in an <img> tag.

Run with the sd.webui python (has CUDA torch):

    set PYTHONPATH=C:\\Users\\kaisa\\AppData\\Local\\sd.webui\\tha3-demo
    C:\\Users\\kaisa\\AppData\\Local\\sd.webui\\system\\python\\python.exe tools\\tha3_service.py

Endpoints:
    GET  /health          -> {"status": "ok"}
    GET  /stream          -> multipart/x-mixed-replace PNG frames (RGBA)
    POST /state           -> {"expression": "happy", "talking": true,
                              "outfit": "standard"}
"""

import io
import json
import math
import os
import random
import sys
import threading
import time

import numpy as np
import torch
from PIL import Image

THA_DIR = r"C:\Users\kaisa\AppData\Local\sd.webui\tha3-demo"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_DIR = os.path.join(PROJECT, "assets", "characters", "aoi")

MODEL = os.environ.get("THA3_MODEL", "separable_half")
FPS = float(os.environ.get("THA3_FPS", "20"))
PORT = int(os.environ.get("THA3_PORT", "8001"))
HOST = os.environ.get("THA3_HOST", "0.0.0.0")

# Face box of the standard neutral sprite (lbpcascade); other outfits use
# the same framing since all sets share the generation seed.
FACE = (206, 107, 189, 189)

sys.path.insert(0, THA_DIR)
os.chdir(THA_DIR)

from tha3.poser.modes.load_poser import load_poser  # noqa: E402

# --- Expression morph presets (pose parameter name -> values) -------------

EXPRESSIONS = {
    "neutral": {},
    "happy": {"eyebrow_happy": [1, 1], "eye_happy_wink": [0.25, 0.25],
              "mouth_raised_corner": [0.8, 0.8]},
    "excited": {"eyebrow_raised": [1, 1], "eye_surprised": [0.35, 0.35],
                "mouth_aaa": [0.55]},
    "curious": {"eyebrow_raised": [0.8, 0.3], "head_y": [0.25],
                "neck_z": [0.15], "mouth_ooo": [0.25]},
    "talking": {"eyebrow_happy": [0.3, 0.3]},
    "laughing": {"eyebrow_happy": [1, 1], "eye_happy_wink": [1, 1],
                 "mouth_aaa": [0.9]},
    "surprised": {"eyebrow_raised": [1, 1], "eye_surprised": [1, 1],
                  "mouth_ooo": [0.7]},
    "thinking": {"eyebrow_serious": [0.5, 0.5], "iris_rotation_x": [0.4],
                 "iris_rotation_y": [0.4], "neck_z": [-0.1]},
    "embarrassed": {"eyebrow_troubled": [0.7, 0.7], "eye_relaxed": [0.35, 0.35],
                    "head_y": [-0.2], "mouth_lowered_corner": [0.3, 0.3]},
    "determined": {"eyebrow_serious": [1, 1],
                   "eye_raised_lower_eyelid": [0.45, 0.45],
                   "mouth_delta": [0.4]},
    "worried": {"eyebrow_troubled": [1, 1],
                "mouth_lowered_corner": [0.55, 0.55]},
    "sleepy": {"eye_relaxed": [0.85, 0.85], "mouth_uuu": [0.3],
               "head_x": [0.1]},
}

MOUTH_KEYS = ["mouth_aaa", "mouth_iii", "mouth_uuu", "mouth_eee", "mouth_ooo"]


class AnimState:
    def __init__(self):
        self.lock = threading.Lock()
        self.expression = "neutral"
        self.talking = False
        self.outfit = "standard"


class Tha3Animator:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[tha3] loading poser '{MODEL}' on {self.device} ...")
        self.poser = load_poser(MODEL, self.device)
        self.size = self.poser.get_image_size()
        self.dtype = self.poser.get_dtype()

        self.param_index = {}
        i = 0
        for g in self.poser.get_pose_parameter_groups():
            self.param_index[g.get_group_name()] = (i, g.get_arity())
            i += g.get_arity()
        self.num_params = i

        self.sources: dict[str, torch.Tensor] = {}
        self.state = AnimState()
        self.frame: bytes = b""
        self.frame_event = threading.Event()

        # idle motion state
        self.next_blink = time.monotonic() + 2.0
        self.blink_until = 0.0
        self.sway_phase = random.random() * math.tau
        self.mouth_current = "mouth_aaa"
        self.mouth_toggle = 0.0

    # --- source image ----------------------------------------------------

    def _load_source(self, outfit: str) -> torch.Tensor:
        if outfit in self.sources:
            return self.sources[outfit]
        path = (os.path.join(CHAR_DIR, "neutral.png") if outfit == "standard"
                else os.path.join(CHAR_DIR, outfit, "neutral.png"))
        if not os.path.exists(path):
            path = os.path.join(CHAR_DIR, "neutral.png")
        sprite = Image.open(path).convert("RGBA")
        head = FACE[2] * 1.35
        scale = 128.0 / head
        scaled = sprite.resize(
            (round(sprite.width * scale), round(sprite.height * scale)),
            Image.LANCZOS,
        )
        fcx = (FACE[0] + FACE[2] / 2) * scale
        fcy = (FACE[1] + FACE[3] / 2) * scale
        canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, (round(256 - fcx), round(128 - fcy)))
        if self.size != 512:
            canvas = canvas.resize((self.size, self.size), Image.LANCZOS)
        arr = np.asarray(canvas).astype(np.float32) / 255.0 * 2.0 - 1.0
        tensor = torch.from_numpy(arr).permute(2, 0, 1).to(self.device)
        if self.dtype == torch.half:
            tensor = tensor.half()
        self.sources[outfit] = tensor
        return tensor

    # --- pose construction -----------------------------------------------

    def _set(self, pose, name, vals):
        if name not in self.param_index:
            return
        start, arity = self.param_index[name]
        for j, v in enumerate(vals[:arity]):
            pose[start + j] = float(v)

    def _build_pose(self) -> torch.Tensor:
        now = time.monotonic()
        pose = torch.zeros(self.num_params, device=self.device)
        if self.dtype == torch.half:
            pose = pose.half()

        with self.state.lock:
            expression = self.state.expression
            talking = self.state.talking

        for name, vals in EXPRESSIONS.get(expression, {}).items():
            self._set(pose, name, vals)

        # breathing + subtle sway
        self._set(pose, "breathing", [0.5 + 0.5 * math.sin(now * 0.9)])
        sway = math.sin(now * 0.35 + self.sway_phase)
        self._set(pose, "head_x", [0.06 * math.sin(now * 0.23)])
        self._set(pose, "body_z", [0.04 * sway])
        self._set(pose, "iris_rotation_y", [0.05 * math.sin(now * 0.15)])

        # blinking (not while eyes are already closed by the expression)
        if expression not in ("laughing", "sleepy"):
            if now >= self.next_blink:
                self.blink_until = now + 0.13
                self.next_blink = now + 2.0 + random.random() * 4.0
            if now < self.blink_until:
                self._set(pose, "eye_wink", [1.0, 1.0])

        # lip flap while talking
        if talking:
            if now >= self.mouth_toggle:
                self.mouth_current = random.choice(MOUTH_KEYS)
                self.mouth_toggle = now + 0.09 + random.random() * 0.1
            for k in MOUTH_KEYS:
                self._set(pose, k, [0.0])
            openness = 0.4 + 0.5 * random.random()
            self._set(pose, self.mouth_current, [openness])

        return pose

    # --- render loop ------------------------------------------------------

    def run(self):
        interval = 1.0 / FPS
        while True:
            t0 = time.monotonic()
            with self.state.lock:
                outfit = self.state.outfit
            source = self._load_source(outfit)
            pose = self._build_pose()
            with torch.inference_mode():
                out = self.poser.pose(source, pose)[0]
            arr = (out.float().permute(1, 2, 0).cpu().numpy() + 1.0) * 0.5
            arr = np.clip(arr * 255, 0, 255).astype(np.uint8)
            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, format="PNG")
            self.frame = buf.getvalue()
            self.frame_event.set()
            self.frame_event.clear()
            elapsed = time.monotonic() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)


# --- HTTP server ----------------------------------------------------------

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

animator = Tha3Animator()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok", "model": MODEL}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/stream":
            self.send_response(200)
            self._cors()
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=thaframe"
            )
            self.end_headers()
            try:
                while True:
                    animator.frame_event.wait(timeout=2.0)
                    frame = animator.frame
                    if not frame:
                        continue
                    self.wfile.write(b"--thaframe\r\n")
                    self.wfile.write(b"Content-Type: image/png\r\n")
                    self.wfile.write(
                        f"Content-Length: {len(frame)}\r\n\r\n".encode()
                    )
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionError, OSError):
                pass
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/state":
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                data = {}
            with animator.state.lock:
                if "expression" in data:
                    animator.state.expression = str(data["expression"])
                if "talking" in data:
                    animator.state.talking = bool(data["talking"])
                if "outfit" in data:
                    animator.state.outfit = str(data["outfit"])
            body = b'{"ok": true}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    threading.Thread(target=animator.run, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[tha3] service on http://{HOST}:{PORT} (model {MODEL}, {FPS} fps)")
    server.serve_forever()


if __name__ == "__main__":
    main()
