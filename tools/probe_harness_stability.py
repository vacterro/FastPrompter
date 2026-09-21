"""T-1288 harness placement probe: bisect the smallest ordered prefix that
makes a known-safe Qt sentinel module die with a native abnormal exit.

Every case runs in ONE fresh blocked subprocess:

    uv run pytest <prefix modules...> <sentinel module> -q -p no:cacheprovider

Classification keeps the native exit code intact (0xC0000005 access
violation, 0xC0000374 heap corruption, abort/exit 3, pytest-timeout kill)
and never reads "no FAIL lines" as success. pytest's own exit 1 (ordinary
test failures) stays a NORMAL termination; native codes do not.

Usage:
    python tools/probe_harness_stability.py order
    python tools/probe_harness_stability.py run --prefix 40 --sentinel tests/test_timer_fire.py
    python tools/probe_harness_stability.py bisect --sentinel tests/test_timer_fire.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LOGDIR = REPO / ".saipen" / "evidence" / "t1288"
RUNNER = ["uv", "run", "pytest"]
NO_CACHE = ["-p", "no:cacheprovider"]

NATIVE_NAMES = {
    -1073741819: "0xC0000005 ACCESS_VIOLATION",
    -1073740940: "0xC0000374 HEAP_CORRUPTION",
    -1073740791: "0xC0000409 STACK_BUFFER_OVERRUN",
    -1073741571: "0xC00000FD STACK_OVERFLOW",
    -1073741510: "0xC000013A CONTROL_C_EXIT",
    -1073741205: "0xC000026B DLL_INIT_FAILED",
}


def module_order(logdir: Path) -> list[str]:
    logdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [*RUNNER, "tests/", "--collect-only", "-q", *NO_CACHE],
        cwd=REPO,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    files: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "::" not in line or not line.startswith("tests"):
            continue
        path = line.split("::", 1)[0].replace("\\", "/")
        if path not in files:
            files.append(path)
    (logdir / "module_order.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    return files


def classify(returncode: int | None, timed_out: bool, tail: str) -> tuple[str, str]:
    if timed_out:
        return "TIMEOUT", "probe process timeout -- killed"
    if returncode == 0:
        return "PASS", "normal pytest exit 0"
    if returncode == 1:
        return "PYTEST_FAIL", "normal pytest exit 1 (test failures)"
    if returncode == 2:
        return "INTERRUPTED", "pytest interrupted"
    if returncode == 5:
        return "NO_TESTS", "no tests collected"
    if returncode is not None and returncode in NATIVE_NAMES:
        return "NATIVE", NATIVE_NAMES[returncode]
    if "Fatal Python error" in tail:
        fatal = re.search(r"Fatal Python error: ([^\r\n]+)", tail)
        return "FATAL", fatal.group(1) if fatal else "Fatal Python error"
    if returncode is not None and returncode < 0:
        return "NATIVE", f"0x{returncode & 0xFFFFFFFF:08X}"
    return "ABNORMAL", f"exit code {returncode}"


def run_case(
    files: list[str],
    sentinel: str,
    *,
    label: str,
    timeout_s: float,
    logdir: Path,
    extra_args: list[str] | None = None,
) -> dict:
    logdir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
    log_path = logdir / f"{safe}.log"
    cmd = [*RUNNER, *files, sentinel, "-q", *(extra_args or []), *NO_CACHE]
    started = time.monotonic()
    timed_out = False
    with open(log_path, "w", encoding="utf-8", errors="replace") as sink:
        sink.write("CMD: " + " ".join(cmd) + "\n\n")
        sink.flush()
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=sink, stderr=subprocess.STDOUT)
        try:
            returncode = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                pass
            returncode = proc.returncode
    elapsed = round(time.monotonic() - started, 1)
    tail = ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail = text[-4000:]
    except OSError:
        pass
    verdict, detail = classify(returncode, timed_out, tail)
    summary = None
    m = re.findall(r"^[=]+ .*? in [0-9.]+s.*$", tail, flags=re.MULTILINE)
    if m:
        summary = m[-1].strip()
    result = {
        "label": label,
        "verdict": verdict,
        "detail": detail,
        "returncode": returncode,
        "elapsed_s": elapsed,
        "prefix_files": len(files),
        "sentinel": sentinel,
        "summary": summary,
        "log": str(log_path),
    }
    with open(logdir / "probe_runs.jsonl", "a", encoding="utf-8") as sink:
        sink.write(json.dumps(result) + "\n")
    return result


def cmd_order(args: argparse.Namespace) -> int:
    logdir = Path(args.logdir)
    files = module_order(logdir)
    print(json.dumps({"modules": len(files), "order_file": str(logdir / "module_order.txt")}))
    for i, f in enumerate(files):
        print(f"{i:4d}  {f}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    logdir = Path(args.logdir)
    files = module_order(logdir) if not args.order_file else [
        line.strip() for line in Path(args.order_file).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    sentinel = args.sentinel.replace("\\", "/")
    prefix = [f for f in files if f != sentinel]
    if args.prefix > len(prefix):
        print(f"prefix {args.prefix} exceeds {len(prefix)} available modules", file=sys.stderr)
        return 2
    result = run_case(
        prefix[: args.prefix],
        sentinel,
        label=args.label or f"run_prefix{args.prefix}",
        timeout_s=args.timeout,
        logdir=logdir,
        extra_args=args.extra_args,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] in ("PASS", "PYTEST_FAIL") else 1


def _abnormal(result: dict) -> bool:
    return result["verdict"] not in ("PASS", "PYTEST_FAIL")


def cmd_bisect(args: argparse.Namespace) -> int:
    logdir = Path(args.logdir)
    files = module_order(logdir) if not args.order_file else [
        line.strip() for line in Path(args.order_file).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    sentinel = args.sentinel.replace("\\", "/")
    if sentinel not in files:
        print(f"sentinel {sentinel} not in collection order", file=sys.stderr)
        return 2
    prefix = [f for f in files if f != sentinel]
    hi = files.index(sentinel)
    print(f"order: {len(files)} modules, sentinel {sentinel} at {files.index(sentinel)}")
    top = run_case(
        prefix[:hi], sentinel, label=f"bisect_top_{hi}", timeout_s=args.timeout, logdir=logdir
    )
    print(json.dumps(top, indent=2))
    if not _abnormal(top):
        print("NO_REPRO: the maximal prefix terminates normally; no placement to bisect")
        return 0
    lo = args.lo
    while lo < hi:
        mid = (lo + hi) // 2
        result = run_case(
            prefix[:mid], sentinel, label=f"bisect_mid_{mid}", timeout_s=args.timeout, logdir=logdir
        )
        print(json.dumps(result, indent=2))
        if _abnormal(result):
            hi = mid
        else:
            lo = mid + 1
    boundary = lo
    final = {"boundary_index": boundary, "boundary_module": prefix[boundary - 1] if boundary else None}
    if boundary > 0:
        for attempt in range(1, args.retries + 1):
            before = run_case(
                prefix[: boundary - 1],
                sentinel,
                label=f"boundary_before_{boundary}_try{attempt}",
                timeout_s=args.timeout,
                logdir=logdir,
            )
            print(json.dumps(before, indent=2))
            if not _abnormal(before):
                break
    for attempt in range(1, args.retries + 1):
        after = run_case(
            prefix[:boundary],
            sentinel,
            label=f"boundary_at_{boundary}_try{attempt}",
            timeout_s=args.timeout,
            logdir=logdir,
        )
        print(json.dumps(after, indent=2))
        if _abnormal(after):
            break
    print(json.dumps(final, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logdir", default=str(DEFAULT_LOGDIR))
    parser.add_argument("--order-file", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("order")

    p_run = sub.add_parser("run")
    p_run.add_argument("--prefix", type=int, required=True)
    p_run.add_argument("--sentinel", required=True)
    p_run.add_argument("--label", default=None)
    p_run.add_argument("--timeout", type=float, default=2700.0)
    p_run.add_argument("--extra-args", nargs=argparse.REMAINDER, default=[])

    p_bisect = sub.add_parser("bisect")
    p_bisect.add_argument("--sentinel", required=True)
    p_bisect.add_argument("--lo", type=int, default=0)
    p_bisect.add_argument("--retries", type=int, default=3)
    p_bisect.add_argument("--timeout", type=float, default=2700.0)

    args = parser.parse_args()
    if args.cmd == "order":
        return cmd_order(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "bisect":
        return cmd_bisect(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
