"""Repeated-play A/B probe for the T-1242 audio corruption (spec 6/7).

Run ON REAL WINDOWS with speakers/headphones.  This is the operator harness
that decides which transport paths are CLEAN and which are CUT / COLOURED /
REVERB-SMEARED; CI cannot listen, so the verdict is recorded by a human.

Modes (T-1242 spec 6/7 matrix):
    raw           A  RAW + POOLED reuse (the reported-defect control)
    fresh         B  RAW + one fresh QSoundEffect per play
    render        C  RENDER + pooled
    fresh_render  D  RENDER + fresh
    padded        E  PADDED + pooled
    fresh_padded  F  PADDED + fresh
    matrix        all six above, in order

Examples:
    uv run python tools/probe_repeated_audio.py --mode raw --plays 20
    uv run python tools/probe_repeated_audio.py --mode fresh --plays 20
    uv run python tools/probe_repeated_audio.py --mode matrix \
        --deferred 1,2,3,10,20

After each play the script pauses and asks you to classify the playback:
    [c]lean  [t]runcated/cut  [k]coloured  [r]everb/smeared  [f]ailed
--deferred keeps those plays silent-recorded and asks for them at the end
(the spec's operator-classified indices: 1,2,3,10,20).
The per-play matrix and the verdict summary are printed at the end and
written to .saipen/probe-repeated-audio-<mode>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6.QtCore import QCoreApplication, QUrl  # noqa: E402
from PyQt6.QtMultimedia import QSoundEffect  # noqa: E402

CLASSIFICATIONS = ("clean", "cut", "coloured", "reverb", "failed")
PROMPT = "classify [c]lean/[t]runcated/[k]oloured/[r]everb/[f]ailed: "

_APP = None  # holds the QCoreApplication alive for the whole run


def _resolve_blip(explicit: str | None) -> str:
    if explicit:
        if not os.path.isfile(explicit):
            raise SystemExit(f"no such file: {explicit}")
        return os.path.abspath(explicit)
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "..", "src", "fastprompter", "sound",
                             "problip", "blip01.wav")
    if not os.path.isfile(candidate):
        raise SystemExit(f"blip01.wav not found at {candidate}")
    return os.path.abspath(candidate)


def _wait_ready(effect) -> None:
    deadline = time.monotonic() + 10.0
    while effect.status() != QSoundEffect.Status.Ready:
        if time.monotonic() > deadline:
            raise SystemExit("source never reached Ready (no audio device?)")
        QCoreApplication.processEvents()
        time.sleep(0.005)


def _wait_finished(effect) -> None:
    """Wait until this cue actually finished (spec 3: one cue at a time).

    The blip is ~67 ms; a 2 s window is generous.  Polls the REAL playing
    state so play #N can never start under play #N-1's tail.
    """
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        try:
            if not effect.isPlaying():
                break
        except Exception:
            break
        time.sleep(0.005)
    QCoreApplication.processEvents()


def _ask(index: int, source: str = "", effect=None) -> str:
    # Non-interactive override for CI smoke / mechanical verification: set
    # FP_PROBE_CLASSIFY=c|t|k|r|f to play the whole matrix without ears.
    # The operator verdict path (real Windows, real ears) still reads stdin.
    auto = os.environ.get("FP_PROBE_CLASSIFY", "").strip().lower()
    if auto:
        for label in CLASSIFICATIONS:
            if label.startswith(auto):
                return label
    while True:
        prompt_str = f"play #{index + 1:02d} {PROMPT}([w]insound reference, [p]replay): "
        answer = input(prompt_str).strip().lower()
        if not answer:
            return "clean"
        if answer in ("w", "win", "winsound", "ref", "reference"):
            try:
                import winsound
                ref_path = source or _resolve_blip(None)
                winsound.PlaySound(ref_path, winsound.SND_FILENAME)
                print(f"  [winsound reference played: {os.path.basename(ref_path)}]")
            except Exception as exc:
                print(f"  [winsound error: {exc}]")
            continue
        if answer in ("p", "play", "replay") and effect is not None:
            try:
                effect.play()
                _wait_finished(effect)
                print("  [replayed current mode]")
            except Exception as exc:
                print(f"  [replay error: {exc}]")
            continue
        for label in CLASSIFICATIONS:
            if label.startswith(answer):
                return label
        print("  ? answer with c/t/k/r/f, 'w' (native winsound ref), or 'p' (replay)")


def _play_and_classify(effect, index: int, pause: float, source: str = "") -> str:
    effect.play()
    _wait_finished(effect)
    time.sleep(pause)
    return _ask(index, source=source, effect=effect)


def run_mode(mode: str, source: str, plays: int, pause: float,
             deferred: tuple[int, ...] = ()) -> dict:
    # Keep a module-level reference: an unreferenced QCoreApplication is
    # garbage-collected by PyQt, which tears down the multimedia backend
    # and every QSoundEffect dies in Loading ("no audio device").
    global _APP
    _APP = QCoreApplication.instance() or QCoreApplication([])
    from fastprompter.core import audio_render

    fresh = "fresh" in mode
    # fresh_render / fresh_padded combine a FRESH effect with the rendered
    # physical source, so render/pad are decided by the SUFFIX, never by
    # the presence of "fresh" in the mode name.
    base = mode[len("fresh_"):] if fresh and mode != "fresh" else (
        "raw" if mode == "fresh" else mode)
    if base == "raw":
        audio_render.set_render_enabled(False)
        audio_render.set_edge_pad_enabled(False)
    elif base == "render":
        audio_render.set_render_enabled(True)
        audio_render.set_edge_pad_enabled(False)
    elif base == "padded":
        audio_render.set_render_enabled(True)
        audio_render.set_edge_pad_enabled(True)
    else:
        raise ValueError(f"unknown mode: {mode}")
    raw = base == "raw"

    physical = source if raw else (
        audio_render.device_ready_wav(source, None) or source)
    print(f"\n== mode {mode}: {plays} plays of "
          f"{os.path.basename(physical)} "
          f"({os.path.basename(source) if physical != source else 'RAW'}), "
          f"{'FRESH effect per play' if fresh else 'POOLED effect reuse'}")

    created: list[QSoundEffect] = []
    pooled: QSoundEffect | None = None
    records = []
    verdicts: dict[int, str] = {}
    for index in range(plays):
        if fresh:
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(physical))
            created.append(effect)
            _wait_ready(effect)
        else:
            if pooled is None:
                pooled = QSoundEffect()
                pooled.setSource(QUrl.fromLocalFile(physical))
                _wait_ready(pooled)
            effect = pooled
        effect.play()
        _wait_finished(effect)
        time.sleep(pause)
        records.append({"play": index + 1, "mode": mode,
                        "physical": os.path.basename(physical),
                        "verdict": ""})
        if (index + 1) not in deferred:
            verdict = _ask(index, source=source, effect=effect)
            records[-1]["verdict"] = verdict
            verdicts[index + 1] = verdict
    for play_no in deferred:
        verdict = _ask(play_no - 1, source=source, effect=effect)
        verdicts[play_no] = verdict
        records[play_no - 1]["verdict"] = verdict
    summary = {label: sum(1 for r in records if r["verdict"] == label)
               for label in CLASSIFICATIONS}
    print(f"\n-- {mode}: {summary}")
    return {"mode": mode, "plays": plays, "physical": physical,
            "records": records, "summary": summary}


def main() -> None:
    # GUI-free audio thread: QSoundEffect works without a platform plugin,
    # and forcing "windows" here would fight the offscreen default some
    # environments set. QCoreApplication only, like the real transport.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", default="raw",
        choices=("raw", "render", "padded", "fresh", "fresh_render",
                 "fresh_padded", "pooled", "all", "matrix"))
    parser.add_argument("--source", default=None,
                        help="WAV to probe (default: blip01.wav)")
    parser.add_argument("--plays", type=int, default=20)
    parser.add_argument("--pause", type=float, default=0.7,
                        help="seconds between play and classification")
    parser.add_argument(
        "--deferred", default="",
        help="comma list of play numbers whose classification is asked at "
             "the end instead of after the play (e.g. 1,2,3,10,20)")
    args = parser.parse_args()

    source = _resolve_blip(args.source)
    deferred = tuple(sorted(
        int(p) for p in args.deferred.split(",") if p.strip()))
    if args.mode in ("all", "matrix"):
        # T-1242 spec 6/7 matrix: RAW/RENDER/PADDED x pooled/fresh.
        modes = ("raw", "fresh", "render", "fresh_render", "padded",
                 "fresh_padded")
    else:
        modes = (args.mode,)
    QCoreApplication([])
    global _APP
    _APP = QCoreApplication.instance() or QCoreApplication([])
    results = []
    try:
        for mode in modes:
            results.append(run_mode(mode, source, args.plays, args.pause,
                                    deferred))
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", ".saipen")
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for result in results:
            path = os.path.join(
                out_dir, f"probe-repeated-audio-{result['mode']}-{stamp}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
            print(f"matrix written: {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
