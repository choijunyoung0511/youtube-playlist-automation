"""Objective, per-track audio quality checks (spec section 8) using librosa.

Scope note: this deliberately only covers checks that make sense for a
single track in isolation (length, intro silence, abrupt volume jumps,
near-silence, short-loop repetition). Cross-track checks from the same
spec section — playlist mood fit and style consistency between songs —
need multiple tracks compared against each other and belong to Phase 3's
playlist-assembly step, not here.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

INTRO_SILENCE_MAX_SEC = 8.0
DURATION_TOLERANCE_RATIO = 0.35  # actual duration must be within +/-35% of the prompt's target
VOLUME_JUMP_THRESHOLD = 1.5  # frame-to-frame RMS jump vs. the track's median RMS
# (librosa's frame_length=2048 window smooths a hard transition over ~4
# hops, so even a real step-change rarely shows the theoretical full-height
# jump; 1.5x the median was calibrated against synthetic fixtures where a
# clean track stays under 0.5 and a real jump clears 2.0 - see
# scripts/phase2_e2e_test.py.)
SILENCE_RMS_THRESHOLD = 0.015  # a frame below this is "silence" for intro detection
MIN_OVERALL_RMS = 0.01  # whole-track average RMS below this = effectively no audio
REPETITION_CORR_THRESHOLD = 0.985  # RMS-envelope self-similarity above this = looping a few seconds


@dataclass
class AudioAnalysisResult:
    duration_sec: float
    intro_silence_sec: float
    max_volume_jump_ratio: float
    overall_rms: float
    repetition_score: float
    issues: list[str]

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0


def analyze_audio(file_path: str, target_duration_sec: int | None = None) -> AudioAnalysisResult:
    y, sr = librosa.load(file_path, sr=None, mono=True)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))

    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    frame_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    overall_rms = float(np.mean(rms))

    above_silence = np.where(rms > SILENCE_RMS_THRESHOLD)[0]
    intro_silence_sec = float(frame_times[above_silence[0]]) if len(above_silence) else duration_sec

    if len(rms) > 1:
        diffs = np.abs(np.diff(rms))
        baseline = float(np.median(rms)) + 1e-6
        max_volume_jump_ratio = float(np.max(diffs)) / baseline
    else:
        max_volume_jump_ratio = 0.0

    repetition_score = _repetition_score(rms, sr, hop_length)

    issues: list[str] = []
    if overall_rms < MIN_OVERALL_RMS:
        issues.append(f"거의 무음 파일로 판단됨 (평균 RMS={overall_rms:.4f})")
    if intro_silence_sec > INTRO_SILENCE_MAX_SEC:
        issues.append(f"인트로 무음이 {intro_silence_sec:.1f}초로 과도함 (기준 {INTRO_SILENCE_MAX_SEC}초)")
    if max_volume_jump_ratio > VOLUME_JUMP_THRESHOLD:
        issues.append(f"갑작스러운 볼륨 변화 감지 (jump ratio={max_volume_jump_ratio:.1f}, 기준 {VOLUME_JUMP_THRESHOLD})")
    if target_duration_sec:
        lower = target_duration_sec * (1 - DURATION_TOLERANCE_RATIO)
        upper = target_duration_sec * (1 + DURATION_TOLERANCE_RATIO)
        if not (lower <= duration_sec <= upper):
            issues.append(f"길이가 목표({target_duration_sec}s)와 크게 다름: 실제 {duration_sec:.1f}s")
    if repetition_score > REPETITION_CORR_THRESHOLD:
        issues.append(f"짧은 구간의 반복이 과도함 (self-similarity={repetition_score:.3f})")

    return AudioAnalysisResult(
        duration_sec=round(duration_sec, 2),
        intro_silence_sec=round(intro_silence_sec, 2),
        max_volume_jump_ratio=round(max_volume_jump_ratio, 2),
        overall_rms=round(overall_rms, 5),
        repetition_score=round(repetition_score, 4),
        issues=issues,
    )


def _repetition_score(rms: np.ndarray, sr: int, hop_length: int) -> float:
    """Peak autocorrelation of the RMS envelope at 1-10s lags. A high value
    means the loudness contour repeats near-identically every few seconds —
    a proxy for "just looping a short clip" rather than genuine musical
    structure over the full track."""
    if len(rms) < 10:
        return 0.0

    mean = float(rms.mean())
    variance = float(np.var(rms))
    # A near-flat envelope (e.g. a sustained pad/drone with no dynamics)
    # has no meaningful periodicity to measure, and its tiny variance makes
    # the correlation below numerically unstable — treat it as "no
    # detectable short-loop repetition" rather than dividing by ~0.
    if mean <= 0 or variance / (mean**2 + 1e-12) < 1e-4:
        return 0.0

    frame_rate = sr / hop_length
    min_lag = max(1, int(1.0 * frame_rate))
    max_lag = min(len(rms) - 1, int(10.0 * frame_rate))
    if max_lag <= min_lag:
        return 0.0

    normed = rms - mean
    denom = float(np.sum(normed**2)) + 1e-9

    best = 0.0
    step = max(1, (max_lag - min_lag) // 20)
    for lag in range(min_lag, max_lag, step):
        corr = float(np.sum(normed[:-lag] * normed[lag:])) / denom
        best = max(best, corr)
    return best
