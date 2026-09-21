"""T-1242 real-Windows listening acceptance for the built-in Space blip.

Plays the EXACT configured Space WAV through two routes on the same machine
and output device:

    REFERENCE   winsound.PlaySound(<original file>)  -- diagnostic only
    PRODUCTION  SoundManager -> AudioHub -> QtSoundTransport (PCM sink path)

and runs the five operator tests of the T-1242 acceptance:

    1 reference        the original WAV, directly            -> REFERENCE_CLEAN?
    2 single           one production cue                    -> SAME AS REFERENCE?
    3 repeated         N cues at a realistic Problip interval -> every one clean?
    4 overlap          a newer cue near the end of the older  -> complete MIX only?
    5 stop             STOP ALL mid-cue, then wait            -> absolute silence?

For every production cue the transport trace is checked mechanically:
request time T0 -> physical start T1 -> finish T2 per request token, no old
request physically started after a newer one, logical == physical source,
rendered == False.  The ears decide the rest.

    uv run python tools/probe_space_fidelity.py
    uv run python tools/probe_space_fidelity.py --tests 1,2 --repeat 10
    uv run python tools/probe_space_fidelity.py --auto   # no prompts

The report is written to .saipen/probe-space-fidelity-<stamp>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "src")))

from PyQt6.QtCore import QCoreApplication  # noqa: E402

_APP = None


def _pump(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        QCoreApplication.processEvents()
        time.sleep(0.002)


def source_identity(path: str) -> dict:
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    with wave.open(path, "rb") as wf:
        frames, rate = wf.getnframes(), wf.getframerate()
        return {"path": os.path.abspath(path), "sha256": digest,
                "channels": wf.getnchannels(), "rate": rate,
                "sample_width": wf.getsampwidth(), "frames": frames,
                "duration_ms": round(frames * 1000 / rate, 1)}


def _ask(prompt: str, auto: bool) -> str:
    if auto:
        return "auto"
    try:
        return input(f"  {prompt} [y/n/notes]: ").strip() or "y"
    except EOFError:
        return "eof"


def _trace_check(transport, tokens: list[str]) -> dict:
    trace = transport.playback_trace()
    starts = {e["token"]: e for e in trace if e.get("event") == "pcm_start"}
    ends = {}
    for e in trace:
        if e.get("event") in ("pcm_finish", "pcm_stop"):
            ends.setdefault(e["token"], e)
    rows, problems = [], []
    for token in tokens:
        start = starts.get(token)
        if start is None:
            problems.append(f"{token}: no physical start (refused or fallback)")
            continue
        end = ends.get(token, {})
        row = {
            "token": token,
            "T1_minus_T0_ms": round((start["t_start"] - start["t_request"]) * 1000, 2),
            "T2_minus_T1_ms": (round((end["t_finish"] - start["t_start"]) * 1000, 1)
                               if end else None),
            "end": end.get("reason", "still playing"),
            "logical_eq_physical": start["logical"] == start["physical"],
            "rendered": start["rendered"],
            "format": start["format"],
        }
        rows.append(row)
        if not row["logical_eq_physical"] or row["rendered"]:
            problems.append(f"{token}: not the RAW source")
        if row["T1_minus_T0_ms"] > 100:
            problems.append(f"{token}: physical start {row['T1_minus_T0_ms']} ms late")
    ordered = sorted((starts[t] for t in tokens if t in starts),
                     key=lambda e: e["t_request"])
    for older, newer in zip(ordered, ordered[1:]):
        if older["t_start"] > newer["t_start"]:
            problems.append(f"{older['token']} started after newer {newer['token']}")
    dupes = [e["token"] for e in trace if e.get("event") == "pcm_start"]
    if len(dupes) != len(set(dupes)):
        problems.append("a request token started twice")
    return {"rows": rows, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tests", default="1,2,3,4,5")
    parser.add_argument("--repeat", type=int, default=8)
    parser.add_argument("--interval", type=float, default=2.5,
                        help="seconds between repeated cues (test 3)")
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument("--source", default=None,
                        help="WAV to test (default: the catalog's Space blip)")
    parser.add_argument("--auto", action="store_true",
                        help="play everything without operator prompts")
    args = parser.parse_args()
    wanted = {int(t) for t in args.tests.split(",") if t.strip()}

    global _APP
    _APP = QCoreApplication.instance() or QCoreApplication([])

    from fastprompter.core import audio_render
    from fastprompter.core.audio_hub import Bus
    from fastprompter.core.sound_manager import SoundManager
    from fastprompter.sound.problip.catalog import resolve_sound_path

    source = args.source or resolve_sound_path("sound_space")
    if not source or not os.path.isfile(source):
        print("Space blip not found through the catalog")
        return 2
    # RAW is the fidelity reference: no render, no padding.
    audio_render.set_render_enabled(False)
    audio_render.set_edge_pad_enabled(False)
    identity = source_identity(source)
    print("SOURCE", json.dumps(identity, indent=1))

    manager = SoundManager(None, {})
    hub = manager.audio_hub()
    transport = hub.transport
    print(f"transport={type(transport).__name__} "
          f"pcm_sink_active={getattr(transport, 'pcm_sink_active', False)}")
    hub.preload([source])
    _pump(0.3)
    duration = identity["duration_ms"] / 1000.0
    report = {"source": identity, "transport": type(transport).__name__,
              "pcm_sink_active": getattr(transport, "pcm_sink_active", False),
              "tests": {}}

    def cue(event="problip_test"):
        result = hub.play_result(source, event=event, bus=Bus.PREVIEW,
                                 mode="mix", volume=args.volume)
        print(f"    {result.request_id}: {result.outcome.value} {result.channel}")
        return result.request_id

    if 1 in wanted:
        print("\nTEST 1 - REFERENCE (winsound, original file)")
        import winsound
        winsound.PlaySound(source, winsound.SND_FILENAME)
        report["tests"]["1_reference"] = {
            "verdict": _ask("REFERENCE_CLEAN?", args.auto)}
        time.sleep(0.5)
    if 2 in wanted:
        print("\nTEST 2 - FASTPROMPTER SINGLE")
        tokens = [cue()]
        _pump(duration + 0.8)
        check = _trace_check(transport, tokens)
        print("   ", check)
        report["tests"]["2_single"] = {
            **check, "verdict": _ask("SAME CHARACTER AS REFERENCE?", args.auto)}
    if 3 in wanted:
        print(f"\nTEST 3 - REPEATED x{args.repeat} every {args.interval}s")
        tokens = []
        for _ in range(args.repeat):
            tokens.append(cue())
            _pump(args.interval)
        check = _trace_check(transport, tokens)
        print("   problems:", check["problems"] or "none")
        report["tests"]["3_repeated"] = {
            **check, "verdict": _ask(
                "every instance like TEST 1, no fragments of earlier plays?",
                args.auto)}
    if 4 in wanted:
        print("\nTEST 4 - OVERLAP (newer cue at 80% of the older)")
        tokens = [cue()]
        _pump(duration * 0.8)
        tokens.append(cue())
        _pump(duration + 1.5)
        check = _trace_check(transport, tokens)
        print("   ", check)
        report["tests"]["4_overlap"] = {
            **check, "verdict": _ask(
                "two complete cues only, no delayed start / orphan tail?",
                args.auto)}
    if 5 in wanted:
        print("\nTEST 5 - STOP ALL mid-cue, then 4 s of silence")
        tokens = [cue(), cue()]
        _pump(0.15)
        hub.stop_all()
        print("    STOP ALL")
        _pump(4.0)
        check = _trace_check(transport, tokens)
        check["active_after"] = transport.active_handles()
        print("   ", check)
        report["tests"]["5_stop"] = {
            **check, "verdict": _ask("absolute silence after STOP ALL?",
                                     args.auto)}

    manager.shutdown()
    out_dir = os.path.join(HERE, "..", ".saipen")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.abspath(os.path.join(
        out_dir, f"probe-space-fidelity-{time.strftime('%Y%m%d-%H%M%S')}.json"))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\nreport: {out}")
    problems = [p for t in report["tests"].values() for p in t.get("problems", [])]
    print("MECHANICAL:", "PASS" if not problems else f"FAIL {problems}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
