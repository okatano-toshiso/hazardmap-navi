#!/usr/bin/env python3
"""Capture submission screenshots of the running app with the locally installed headless Chrome.

Start the app first, e.g. for real AI output shown with consent pre-ticked (visible on screen):
    HINAN_AI_PROVIDER=claude HINAN_DEMO_CONSENT=1 uv run python -m hinan
then:
    uv run python scripts/capture_screenshots.py
Uses only the standard library, Pillow and Google Chrome; nothing is added to the project.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SHOTS = {
    "0-overview-konohana": "?area=konohana&hazard=tsunami",
    "1-tsunami-nishikujo": "?lat=34.68241&lon=135.4705&hazard=tsunami",
    "2-storm-surge-no-site": "?lat=34.674039&lon=135.443735&hazard=storm_surge",
    "3-flood-yashio": "?lat=35.82435&lon=139.8367&hazard=flood",
    "4-flood-misato": "?lat=35.82481&lon=139.87024&hazard=flood",
    "5-out-of-area": "?lat=34.7025&lon=135.4959&hazard=tsunami",
    "6-chat-assistant": "?lat=34.674039&lon=135.443735&hazard=storm_surge&ask=1",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765/")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/submission/screenshots")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, query in SHOTS.items():
        target = args.out / f"{name}.png"
        with tempfile.TemporaryDirectory(prefix="hinan-shot-") as profile:
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                            f"--user-data-dir={profile}", "--window-size=1400,1300", "--virtual-time-budget=30000",
                            f"--screenshot={target}", args.base + query], check=True, capture_output=True, timeout=180)
        image = Image.open(target).convert("RGB")
        background = Image.new("RGB", image.size, image.getpixel((image.width - 1, image.height - 1)))
        box = ImageChops.difference(image, background).getbbox()
        if box:
            image.crop((0, 0, image.width, min(image.height, box[3] + 40))).save(target)
        print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
