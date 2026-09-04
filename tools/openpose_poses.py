"""Render OpenPose skeleton control images for the 6 sprite poses.

All poses share head position, torso and foot line so the generated
bodies are interchangeable (see docs/ASSET_PIPELINE.md). Output:
tools/poses/<pose>.png, 640x1536, standard OpenPose COCO-18 colors.
"""

import math
import os

from PIL import Image, ImageDraw

W, H = 640, 1536
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poses")

# Shared skeleton (image coords; OpenPose "R" = person's right = image left)
BASE = {
    "nose": (300, 200),
    "neck": (310, 335),
    "r_sho": (248, 345), "l_sho": (372, 345),
    "r_hip": (272, 770), "l_hip": (352, 770),
    "r_knee": (268, 1070), "l_knee": (356, 1070),
    "r_ank": (264, 1400), "l_ank": (360, 1400),
    "r_eye": (283, 183), "l_eye": (321, 183),
    "r_ear": (266, 198), "l_ear": (338, 198),
}

# Per-pose arm keypoints: (r_elb, r_wri, l_elb, l_wri)
ARMS = {
    "stand":         ((238, 505), (232, 655), (382, 505), (388, 655)),
    "wave":          ((212, 300), (248, 168), (382, 505), (388, 655)),
    "arms_crossed":  ((228, 480), (348, 468), (392, 480), (272, 468)),
    "hands_clasped": ((242, 505), (298, 610), (378, 505), (326, 610)),
    "pointing":      ((175, 385), (72, 355), (382, 505), (388, 655)),
    "phone":         ((230, 470), (272, 235), (382, 505), (388, 655)),
}

# COCO-18 keypoint order used by ControlNet OpenPose
KP_ORDER = [
    "nose", "neck", "r_sho", "r_elb", "r_wri", "l_sho", "l_elb", "l_wri",
    "r_hip", "r_knee", "r_ank", "l_hip", "l_knee", "l_ank",
    "r_eye", "l_eye", "r_ear", "l_ear",
]

# limbSeq / colors from the reference draw_bodypose implementation (1-indexed)
LIMB_SEQ = [
    [2, 3], [2, 6], [3, 4], [4, 5], [6, 7], [7, 8], [2, 9], [9, 10],
    [10, 11], [2, 12], [12, 13], [13, 14], [2, 1], [1, 15], [15, 17],
    [1, 16], [16, 18],
]
COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 255), (255, 0, 170), (255, 0, 85),
]
STICK_W = 6
JOINT_R = 7


def draw_limb(draw, p1, p2, color):
    """Draw a limb as a rotated ellipse (like the reference renderer)."""
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    length = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 2
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    steps = max(int(length * 2), 1)
    dim = tuple(int(c * 0.6) for c in color)
    for i in range(steps + 1):
        t = i / steps - 0.5
        x = mx + math.cos(angle) * length * 2 * t
        y = my + math.sin(angle) * length * 2 * t
        draw.ellipse([x - STICK_W, y - STICK_W, x + STICK_W, y + STICK_W],
                     fill=dim)


def render_pose(name: str) -> str:
    r_elb, r_wri, l_elb, l_wri = ARMS[name]
    kps = dict(BASE, r_elb=r_elb, r_wri=r_wri, l_elb=l_elb, l_wri=l_wri)
    pts = [kps[k] for k in KP_ORDER]

    im = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(im)
    for (a, b), color in zip(LIMB_SEQ, COLORS):
        draw_limb(draw, pts[a - 1], pts[b - 1], color)
    for pt, color in zip(pts, COLORS):
        draw.ellipse([pt[0] - JOINT_R, pt[1] - JOINT_R,
                      pt[0] + JOINT_R, pt[1] + JOINT_R], fill=color)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    im.save(path)
    return path


if __name__ == "__main__":
    for pose in ARMS:
        print("rendered", render_pose(pose))
