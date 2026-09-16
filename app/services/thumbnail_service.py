"""Renders a placeholder thumbnail image (spec section 11).

Like the video background, this is procedural Pillow art, not a real
AI-generated image - there's no image-generation API wired up yet. What
Phase 4 actually needs is the *prompt* (from AiProvider.generate_thumbnail_prompt,
stored on Playlist.thumbnail_prompt) and a usable placeholder to review in
the admin UI; swapping in a real image-gen provider later only touches
this one function.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .video_service import FONT_PATH, HEIGHT, WIDTH, generate_background_image


def render_thumbnail_image(mood: str, text: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg_path = out_path.parent / f"_{out_path.stem}_bg.png"
    generate_background_image(mood, bg_path)

    img = Image.open(bg_path).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    font_size = 64
    if FONT_PATH:
        font = ImageFont.truetype(FONT_PATH, font_size)
    else:
        # No Korean-capable font found on this system - fall back rather than
        # crash; Korean text will render as boxes until VIDEO_FONT_PATH is set.
        font = ImageFont.load_default(size=font_size)
    lines = _wrap_text(draw, text.split(), font, max_width=WIDTH - 120)

    line_height = font_size + 14
    total_height = line_height * len(lines) + 40
    top = HEIGHT - total_height - 40

    draw.rectangle([0, top - 20, WIDTH, HEIGHT], fill=(0, 0, 0, 140))
    y = top
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    img.convert("RGB").save(out_path)
    bg_path.unlink(missing_ok=True)
    return out_path


def _wrap_text(draw: ImageDraw.ImageDraw, words: list[str], font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]
