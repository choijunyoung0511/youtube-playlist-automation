"""Concatenates a Playlist's ordered tracks into one audio file with short
crossfades between songs (spec section 9)."""

import shutil
import subprocess
from pathlib import Path

from ..models import Playlist

DEFAULT_CROSSFADE_SEC = 3


def assemble_playlist_audio(playlist: Playlist, output_path: Path, crossfade_sec: int = DEFAULT_CROSSFADE_SEC) -> float:
    track_links = sorted(playlist.track_links, key=lambda pt: pt.position)
    if not track_links:
        raise ValueError(f"Playlist {playlist.id} has no tracks to assemble")

    file_paths = [tl.track.audio_path for tl in track_links]
    if any(p is None for p in file_paths):
        raise ValueError("Every track in the playlist must have audio_path set before assembly")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(file_paths) == 1:
        shutil.copy(file_paths[0], output_path)
    else:
        inputs: list[str] = []
        for p in file_paths:
            inputs += ["-i", p]

        filter_parts = []
        prev_label = "0"
        for idx in range(1, len(file_paths)):
            out_label = f"cf{idx}"
            filter_parts.append(f"[{prev_label}][{idx}]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[{out_label}]")
            prev_label = out_label

        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", f"[{prev_label}]",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return _probe_duration(output_path)


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())
