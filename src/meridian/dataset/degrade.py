"""This module adds scanner artifacts that are deterministic in each record's seed."""
from __future__ import annotations

import random

from PIL import Image, ImageFilter


def degrade(img: Image.Image, r: dict) -> Image.Image:
    """This function applies scan artifacts that are deterministic in the
    record's seed."""
    rng = random.Random(r["seed"] + 7)
    if r.get("rotation"):
        img = img.rotate(r["rotation"], resample=Image.BICUBIC, fillcolor=248)
    if r.get("blur"):
        img = img.filter(ImageFilter.GaussianBlur(r["blur"]))
    if r.get("fade"):
        # This simulates faded toner by compressing the range toward white so
        # that strokes thin out.
        fade = r["fade"]
        img = img.point(lambda v: int(255 - (255 - v) * fade))
    if r.get("noise"):
        px = img.load()
        amp = r["noise"]
        for yy in range(img.height):
            for xx in range(img.width):
                v = px[xx, yy] + rng.randint(-amp, amp)
                px[xx, yy] = 0 if v < 0 else (255 if v > 255 else v)
    if r.get("speckle"):
        px = img.load()
        n = int(img.width * img.height * r["speckle"])
        for _ in range(n):
            xx, yy = rng.randint(0, img.width - 1), rng.randint(0, img.height - 1)
            px[xx, yy] = 0 if rng.random() < 0.5 else 255
    return img
