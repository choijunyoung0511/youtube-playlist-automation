"""Turns a Playlist's assembled audio into a 16:9 background video (spec
section 10): a still image with slow Ken Burns zoom, a subtle looping
particle layer (rain/snow/dust keyed to mood) so it's never a single
static frame, and the playlist title burned in.

The background artwork here is deliberately simple procedural gradient
art, not AI-generated - real thumbnail/art generation is Phase 4's job.
This service only needs *something* to zoom/pan over to prove the video
pipeline end-to-end.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 1280, 720


def _resolve_font_path() -> str | None:
    """Finds a font with Korean (Hangul) glyph support across platforms -
    a hardcoded Linux path here previously broke this entirely on Windows/
    macOS. VIDEO_FONT_PATH lets anyone override it explicitly."""
    override = os.getenv("VIDEO_FONT_PATH")
    if override and Path(override).exists():
        return override

    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Debian/Ubuntu fonts-noto-cjk
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        r"C:\Windows\Fonts\malgun.ttf",  # Windows - Malgun Gothic, bundled since Vista
        r"C:\Windows\Fonts\malgunbd.ttf",
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",  # macOS
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None  # caller falls back to a font-less/default rendering path rather than crashing


FONT_PATH = _resolve_font_path()


def _ffmpeg_escape_path(path: str) -> str:
    """ffmpeg filtergraph values treat ':' and '\\' as syntax, which a raw
    Windows path (C:\\Windows\\Fonts\\malgun.ttf) is full of."""
    return path.replace("\\", "/").replace(":", r"\:")

MOOD_PALETTES = {
    "차분한": ((20, 30, 60), (45, 65, 100)),
    "몽환적인": ((35, 20, 65), (90, 50, 140)),
    "따뜻한": ((60, 30, 20), (140, 85, 45)),
    "잔잔한": ((20, 40, 50), (55, 90, 100)),
    "약간 신비로운": ((30, 20, 60), (85, 45, 125)),
    "포근한": ((50, 30, 30), (120, 70, 60)),
    "느긋한": ((25, 45, 55), (60, 100, 110)),
}
DEFAULT_PALETTE = ((20, 25, 40), (55, 65, 95))

RAIN_MOODS = {"차분한", "잔잔한"}
SNOW_MOODS = {"몽환적인", "약간 신비로운"}


def generate_background_image(mood: str, out_path: Path) -> Path:
    top, bottom = MOOD_PALETTES.get(mood, DEFAULT_PALETTE)
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _particle_kind_for_mood(mood: str) -> str:
    if mood in RAIN_MOODS:
        return "rain"
    if mood in SNOW_MOODS:
        return "snow"
    return "dust"


def generate_particle_overlay(mood: str, out_path: Path, num_frames: int = 40, fps: int = 20) -> Path:
    """Renders particles as bright shapes on a solid black background and
    relies on 'screen' blending at composite time (black contributes
    nothing, bright pixels add light) rather than a real alpha channel -
    this ffmpeg build's libvpx-vp9 silently drops alpha even when asked
    for yuva420p, which made an earlier alpha-overlay version render as
    solid black. Plain libx264/yuv420p + screen blend has no such gap."""
    kind = _particle_kind_for_mood(mood)
    tmp_dir = Path(tempfile.mkdtemp(prefix="particles_"))
    rng = random.Random(42)
    num_particles = {"rain": 70, "snow": 40, "dust": 25}[kind]
    particles = [
        {
            "x": rng.uniform(0, WIDTH),
            "y": rng.uniform(0, HEIGHT),
            "speed": rng.uniform(6, 14) if kind == "rain" else rng.uniform(0.5, 2.5),
            "drift": rng.uniform(-0.5, 0.5),
        }
        for _ in range(num_particles)
    ]

    try:
        for frame_idx in range(num_frames):
            frame = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
            draw = ImageDraw.Draw(frame)
            for p in particles:
                y = (p["y"] + frame_idx * p["speed"]) % HEIGHT
                x = (p["x"] + frame_idx * p["drift"]) % WIDTH
                if kind == "rain":
                    draw.line([(x, y), (x - 2, y + 14)], fill=(120, 140, 180), width=1)
                elif kind == "snow":
                    r = 2.5
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=(180, 180, 190))
                else:
                    r = 1.5
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=(140, 130, 100))
            frame.save(tmp_dir / f"frame_{frame_idx:03d}.png")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-framerate", str(fps),
                "-i", str(tmp_dir / "frame_%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(out_path),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return out_path


def compose_video(
    background_image: Path,
    particle_overlay: Path,
    audio_path: Path,
    title_text: str,
    out_path: Path,
    duration_sec: float,
) -> Path:
    safe_title = title_text.replace("'", "").replace(":", " -")
    font_clause = f"fontfile={_ffmpeg_escape_path(FONT_PATH)}:" if FONT_PATH else ""
    filter_complex = (
        f"[0:v]scale={WIDTH}:{HEIGHT},"
        f"zoompan=z='min(zoom+0.0006,1.3)':d=1:s={WIDTH}x{HEIGHT}:fps=25[bg];"
        f"[1:v]loop=loop=-1:size=32767[p];"
        f"[bg][p]blend=all_mode=screen:shortest=1[bgp];"
        f"[bgp]drawtext={font_clause}text='{safe_title}':"
        f"fontcolor=white@0.9:fontsize=32:x=40:y=h-70:box=1:boxcolor=black@0.35:boxborderw=12[vout]"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(background_image),
        "-i", str(particle_overlay),
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "2:a",
        "-t", str(duration_sec),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path
