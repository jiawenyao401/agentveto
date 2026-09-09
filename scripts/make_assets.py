#!/usr/bin/env python3
"""Generate README hero images from the bundled HTML demos.

Outputs (under docs/img/):
  - hero.png             a 1600x900 hero showing the v0 report (cost + timeline)
  - hero-veto.png        the same view of the Veto demo (deny rows highlighted)
  - timeline.png         the timeline panel only, cropped tight

Why this script exists:
  README thumbnails matter on launch day. Most viewers will never open the
  HTML; the still image is the one chance to make them curious.

Usage:
  python scripts/make_assets.py

Requires: playwright + chromium already installed (pip install playwright;
playwright install chromium).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)


def ensure_demos() -> tuple[Path, Path]:
    """Make sure the two canonical demo reports exist on disk."""
    import agentveto

    v0 = Path(agentveto.demo(out=None))
    veto = Path(agentveto.demo_veto(out=None))
    return v0, veto


def shoot(url: str, out: Path, *, w: int, h: int, clip: dict | None = None) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2)
        page = ctx.new_page()
        page.goto("file://" + str(url))
        page.wait_for_selector("#rows .row", state="visible", timeout=15_000)
        page.wait_for_timeout(600)  # let fonts and metrics settle
        kwargs = {"path": str(out), "type": "png"}
        if clip:
            kwargs["clip"] = clip
        else:
            kwargs["full_page"] = False
        page.screenshot(**kwargs)
        browser.close()
    print(f"  wrote {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


def composite(fg: Path, bg: Path, out: Path, *, label: str, label_color=(20, 24, 32)) -> None:
    """Stack the demo screenshot on top of a labeled backdrop, save hero PNG."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(fg).convert("RGBA")
    canvas_w, canvas_h = 1600, 900
    bg_img = Image.new("RGB", (canvas_w, canvas_h), (245, 247, 250))
    # Fit foreground
    ratio = min(canvas_w / img.width, canvas_h / img.height)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    img = img.resize(new_size, Image.LANCZOS)
    x = (canvas_w - img.width) // 2
    y = (canvas_h - img.height) // 2
    # Drop shadow
    shadow = Image.new("RGBA", (img.width + 20, img.height + 20), (0, 0, 0, 0))
    shadow.paste(img, (10, 10), img)
    bg_img.paste(shadow, (x - 10, y - 10), shadow)
    bg_img.paste(img, (x, y))
    # Label
    draw = ImageDraw.Draw(bg_img)
    try:
        font = ImageFont.truetype("seguisb.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle([(24, 24), (24 + 360, 70)], fill=(255, 255, 255), outline=label_color, width=1)
    draw.text((36, 34), label, fill=label_color, font=font)
    bg_img.save(out, "PNG", optimize=True)
    print(f"  hero -> {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


def main() -> int:
    print("ensuring demos are built...")
    v0, veto = ensure_demos()

    print("\nshooting raw frames (2x dpi)...")
    raw_v0 = OUT / "_raw_v0.png"
    raw_veto = OUT / "_raw_veto.png"
    shoot(str(v0), raw_v0, w=1400, h=900)
    shoot(str(veto), raw_veto, w=1400, h=900)

    print("\ncomposing hero cards...")
    composite(raw_v0, None, OUT / "hero.png", label="agentveto · Replay it.")
    composite(raw_veto, None, OUT / "hero-veto.png", label="agentveto · Prove it. Veto it.")

    # Cleanup intermediates
    raw_v0.unlink(missing_ok=True)
    raw_veto.unlink(missing_ok=True)

    print("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
