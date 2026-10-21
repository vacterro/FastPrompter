#!/usr/bin/env python3
"""Generate the redistributable fallback sound pack.

Every file here is synthesized from first principles: sine partials, shaped
noise and envelopes computed in this script.  No recording, sample, game
asset or third-party waveform is read, so the output is original material
that can be redistributed with the application.

The generator is deterministic: the same file name always produces the same
bytes, which keeps the packaged manifest stable across builds and machines.

Usage:
    python scripts/generate_redistributable_sounds.py --out sounds
"""

from __future__ import annotations

import argparse
import hashlib
import math
import struct
import sys
import wave
from pathlib import Path

SAMPLE_RATE = 22050
PEAK = 0.5  # -6 dBFS keeps the pack quiet next to user material.


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _rng(seed: int):
    """xorshift32: deterministic, dependency-free noise."""
    state = seed & 0xFFFFFFFF or 0x9E3779B9

    def nxt() -> float:
        nonlocal state
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        return (state / 0xFFFFFFFF) * 2.0 - 1.0

    return nxt


def _env_exp(n: int, attack: float, tau: float) -> list[float]:
    """Attack ramp then exponential decay, both in seconds."""
    attack_n = max(1, int(attack * SAMPLE_RATE))
    out = []
    for i in range(n):
        if i < attack_n:
            a = i / attack_n
        else:
            a = math.exp(-(i - attack_n) / (tau * SAMPLE_RATE))
        out.append(a)
    return out


def _sine(freq: float, n: int, phase: float = 0.0) -> list[float]:
    step = 2.0 * math.pi * freq / SAMPLE_RATE
    return [math.sin(phase + step * i) for i in range(n)]


def _sweep(f0: float, f1: float, n: int) -> list[float]:
    """Exponential frequency sweep (constant perceived pitch rate)."""
    out = []
    phase = 0.0
    ratio = (f1 / f0) ** (1.0 / max(1, n - 1)) if f1 > 0 and f0 > 0 else 1.0
    freq = f0
    for _ in range(n):
        phase += 2.0 * math.pi * freq / SAMPLE_RATE
        out.append(math.sin(phase))
        freq *= ratio
    return out


def _noise_burst(n: int, seed: int, smooth: int = 1) -> list[float]:
    nxt = _rng(seed)
    raw = [nxt() for _ in range(n)]
    if smooth <= 1:
        return raw
    out = []
    acc = 0.0
    for value in raw:
        acc += (value - acc) / smooth
        out.append(acc)
    return out


def _lowpass(samples: list[float], alpha: float) -> list[float]:
    out = []
    acc = 0.0
    for value in samples:
        acc += alpha * (value - acc)
        out.append(acc)
    return out


def _mix(*layers: tuple[list[float], float]) -> list[float]:
    n = max(len(layer) for layer, _ in layers)
    out = [0.0] * n
    for layer, gain in layers:
        for i, value in enumerate(layer):
            out[i] += value * gain
    return out


def _concat(parts: list[list[float]], gap_s: float = 0.0) -> list[float]:
    out: list[float] = []
    gap = [0.0] * int(gap_s * SAMPLE_RATE)
    for index, part in enumerate(parts):
        if index:
            out.extend(gap)
        out.extend(part)
    return out


def _limit(samples: list[float]) -> list[float]:
    peak = max((abs(v) for v in samples), default=0.0)
    if peak <= 0.0:
        return samples
    gain = PEAK / peak
    return [math.tanh(v * gain * 1.05) * (PEAK / max(0.999, PEAK)) for v in samples]


def _fade_edges(samples: list[float], ms: float = 3.0) -> list[float]:
    n = int(SAMPLE_RATE * ms / 1000.0)
    if n <= 0 or len(samples) < 2 * n:
        return samples
    out = list(samples)
    for i in range(n):
        g = i / n
        out[i] *= g
        out[-1 - i] *= g
    return out


# ---------------------------------------------------------------------------
# Voices: each returns a float list in [-1, 1]
# ---------------------------------------------------------------------------


def voice_click(seed: int, freq: float = 900.0, dur: float = 0.045) -> list[float]:
    n = int(dur * SAMPLE_RATE)
    tone = [s * e for s, e in zip(_sine(freq, n), _env_exp(n, 0.0008, 0.010))]
    noise = [
        s * e
        for s, e in zip(
            _lowpass(_noise_burst(n, seed), 0.35), _env_exp(n, 0.0002, 0.004)
        )
    ]
    return _limit(_mix((tone, 0.85), (noise, 0.25)))


def voice_tick(seed: int, freq: float = 1500.0) -> list[float]:
    n = int(0.028 * SAMPLE_RATE)
    tone = [s * e for s, e in zip(_sine(freq, n), _env_exp(n, 0.0005, 0.005))]
    return _limit(_mix((tone, 1.0), (_noise_burst(n, seed), 0.15)))


def voice_toggle(seed: int, rising: bool) -> list[float]:
    n = int(0.07 * SAMPLE_RATE)
    f0, f1 = (520.0, 880.0) if rising else (880.0, 520.0)
    tone = [s * e for s, e in zip(_sweep(f0, f1, n), _env_exp(n, 0.002, 0.030))]
    return _limit(tone)


def voice_bell(seed: int, base: float = 660.0, dur: float = 0.55) -> list[float]:
    n = int(dur * SAMPLE_RATE)
    partials = ((1.0, 1.0), (2.01, 0.42), (3.02, 0.20), (4.97, 0.09))
    layers = []
    for ratio, gain in partials:
        tone = _sine(base * ratio, n, phase=(seed % 628) / 100.0)
        decay = _env_exp(n, 0.003, dur * 0.30 / math.sqrt(ratio))
        layers.append(([s * e for s, e in zip(tone, decay)], gain))
    return _limit(_mix(*layers))


def voice_chime(seed: int, notes: tuple[float, ...], step: float = 0.085) -> list[float]:
    parts = [voice_bell(seed + i, freq, 0.42) for i, freq in enumerate(notes)]
    return _limit(_concat(parts, gap_s=step * 0.30))


def voice_success(seed: int) -> list[float]:
    return voice_chime(seed, (523.25, 659.25, 783.99, 1046.50))


def voice_coin(seed: int) -> list[float]:
    a = voice_bell(seed, 987.77, 0.16)
    b = voice_bell(seed + 1, 1318.51, 0.30)
    return _limit(_concat([a, b], gap_s=0.045))


def voice_warn(seed: int) -> list[float]:
    n = int(0.34 * SAMPLE_RATE)
    tone = [s * e for s, e in zip(_sine(220.0, n), _env_exp(n, 0.010, 0.14))]
    sub = [s * e for s, e in zip(_sine(110.0, n), _env_exp(n, 0.010, 0.18))]
    pulse = _sine(9.0, n)
    shaped = [t * (0.75 + 0.25 * p) for t, p in zip(tone, pulse)]
    return _limit(_mix((shaped, 1.0), (sub, 0.45)))


def voice_error(seed: int) -> list[float]:
    a = voice_bell(seed, 311.13, 0.22)
    b = voice_bell(seed + 7, 233.08, 0.30)
    return _limit(_concat([a, b], gap_s=0.03))


def voice_timer(seed: int) -> list[float]:
    return voice_bell(seed, 880.0, 0.50)


def voice_notify(seed: int) -> list[float]:
    return voice_chime(seed, (880.0, 1174.66), step=0.06)


def voice_whoosh(seed: int) -> list[float]:
    n = int(0.32 * SAMPLE_RATE)
    noise = _lowpass(_noise_burst(n, seed, smooth=3), 0.22)
    shape = []
    for i in range(n):
        x = i / n
        shape.append((math.sin(math.pi * x) ** 1.6))
    return _limit([v * s for v, s in zip(noise, shape)])


def voice_panel(seed: int, opening: bool) -> list[float]:
    n = int(0.13 * SAMPLE_RATE)
    f0, f1 = (300.0, 620.0) if opening else (620.0, 300.0)
    tone = [s * e for s, e in zip(_sweep(f0, f1, n), _env_exp(n, 0.004, 0.055))]
    return _limit(tone)


def voice_pad(seed: int, base: float = 196.0, dur: float = 0.9) -> list[float]:
    n = int(dur * SAMPLE_RATE)
    parts = []
    for ratio, gain in ((1.0, 0.6), (1.5, 0.25), (2.0, 0.15)):
        tone = _sine(base * ratio, n, phase=(seed % 314) / 50.0)
        parts.append((tone, gain))
    swell = _env_exp(n, dur * 0.35, dur * 0.5)
    return _limit([v * s for v, s in zip(_mix(*parts), swell)])


def voice_blip(seed: int, base: float) -> list[float]:
    n = int(0.055 * SAMPLE_RATE)
    tone = [s * e for s, e in zip(_sine(base, n), _env_exp(n, 0.001, 0.018))]
    return _limit(tone)


def voice_pop(seed: int) -> list[float]:
    n = int(0.075 * SAMPLE_RATE)
    body = [s * e for s, e in zip(_sweep(760.0, 240.0, n), _env_exp(n, 0.001, 0.020))]
    return _limit(body)


def voice_scratch(seed: int) -> list[float]:
    n = int(0.22 * SAMPLE_RATE)
    noise = _lowpass(_noise_burst(n, seed, smooth=2), 0.5)
    shape = [math.exp(-i / (0.03 * SAMPLE_RATE)) for i in range(n)]
    return _limit([v * s for v, s in zip(noise, shape)])


def voice_type_key(seed: int) -> list[float]:
    n = int(0.030 * SAMPLE_RATE)
    click = _noise_burst(n, seed, smooth=2)
    thud = _sine(180.0, n)
    return _limit(
        _mix(
            ([v * e for v, e in zip(click, _env_exp(n, 0.0003, 0.006))], 0.55),
            ([v * e for v, e in zip(thud, _env_exp(n, 0.001, 0.010))], 0.45),
        )
    )


# ---------------------------------------------------------------------------
# Name -> voice table
# ---------------------------------------------------------------------------

CLICK_WORDS = ("click", "button", "btn", "press", "menu", "mnu")
TICK_WORDS = ("tick", "key", "type", "cursor", "select")
BELL_WORDS = ("bell", "ding", "chime", "timer")
SUCCESS_WORDS = ("success", "complete", "done", "levelup", "win", "score", "vote")
COIN_WORDS = ("coin", "kaching", "money", "cart", "cash")
WARN_WORDS = ("warn", "alert", "deny", "denied", "error", "fail", "block", "hurt")
WHOOSH_WORDS = ("whoosh", "swish", "swoosh", "wind")
NOTIFY_WORDS = ("notify", "notification", "message", "msg", "mail")
POP_WORDS = ("pop", "blip", "bonk", "boop")
SCRATCH_WORDS = ("scratch", "glitch", "static")
OPEN_WORDS = ("open", "launch", "show", "expand")
CLOSE_WORDS = ("close", "collapse", "exit", "hide")
SWITCH_WORDS = ("switch", "toggle", "on", "off")


def synthesize(name: str) -> list[float]:
    """Pick a voice for ``name`` and render it deterministically."""
    stem = Path(name).stem.lower()
    seed = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)
    base_note = 196.0 * (2.0 ** ((seed % 12) / 12.0))  # chromatic but always musical

    def has(words) -> bool:
        return any(word in stem for word in words)

    if has(COIN_WORDS):
        return voice_coin(seed)
    if has(SUCCESS_WORDS):
        return voice_success(seed)
    if has(WARN_WORDS):
        return voice_error(seed) if has(("error", "fail", "deny", "denied", "block")) else voice_warn(seed)
    if has(BELL_WORDS):
        return voice_timer(seed)
    if has(NOTIFY_WORDS):
        return voice_notify(seed)
    if has(WHOOSH_WORDS):
        return voice_whoosh(seed)
    if has(SCRATCH_WORDS):
        return voice_scratch(seed)
    if has(POP_WORDS):
        return voice_pop(seed)
    if has(OPEN_WORDS):
        return voice_panel(seed, opening=True)
    if has(CLOSE_WORDS):
        return voice_panel(seed, opening=False)
    if has(("undo", "back", "previous", "prev")):
        return voice_toggle(seed, rising=False)
    if has(("redo", "next", "forward")):
        return voice_toggle(seed, rising=True)
    if has(TICK_WORDS):
        return voice_type_key(seed) if "key" in stem or "type" in stem else voice_tick(seed, 1200.0 + (seed % 500))
    if has(CLICK_WORDS):
        return voice_click(seed, 700.0 + (seed % 700))
    if has(("loop", "ambient", "battle", "pad", "hum", "drone")):
        return voice_pad(seed, base_note, 0.9)
    return voice_blip(seed, 440.0 + (seed % 8) * 55.0)


# ---------------------------------------------------------------------------
# WAV writer
# ---------------------------------------------------------------------------


def write_wav(path: Path, samples: list[float], sample_rate: int = SAMPLE_RATE) -> None:
    samples = _fade_edges(_limit(samples))
    frames = bytearray()
    for value in samples:
        clamped = max(-1.0, min(1.0, value))
        frames.extend(struct.pack("<h", int(round(clamped * 32767))))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(bytes(frames))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def read_names_file(path: Path) -> list[str]:
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.replace("\\", "/"))
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="output sound directory")
    parser.add_argument("--names", required=True, type=Path, help="file with one relative name per line")
    parser.add_argument("--check", action="store_true", help="verify instead of write")
    args = parser.parse_args(argv)

    names = read_names_file(args.names)
    if not names:
        print("no names given", file=sys.stderr)
        return 2

    problems = 0
    for rel in names:
        target = args.out / rel
        if args.check:
            if not target.is_file():
                print(f"MISSING {rel}", file=sys.stderr)
                problems += 1
            continue
        write_wav(target, synthesize(rel))
    if args.check:
        print(f"{len(names) - problems}/{len(names)} fallback sounds present")
        return 1 if problems else 0
    print(f"generated {len(names)} synthesized sounds into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
