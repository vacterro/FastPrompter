"""T-1350: for the tickets whose verify clause names no test file, find the
narrowest test that actually exercises the ticket's subject. Read-only: it
searches tests/ for the distinctive identifiers the clause names, so the
reverify command is chosen from evidence instead of guessed."""

import io
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS = os.path.join(ROOT, "tests")

# ticket -> distinctive tokens its clause names (module paths, symbol names,
# feature words). A test that mentions the tokens exercises the subject.
PROBES = {
    "T-1297": ["VERSION", "sync_release_version", "product-version"],
    "T-1295": ["default_profile", "format_default_profile"],
    "T-1267": ["LimitSettingsDialog", "claude", "source_path"],
    "T-1260": ["shutdown_ownership", "timer_isolation", "scaled_cache"],
    "T-1268": ["attribution", "CLAUDE_CONFIG_DIR", "organization"],
    "T-1261": ["delete", "cue", "defer_ui"],
    "T-1265": ["clock", "advance", "now_provider", "persistence"],
    "T-1256": ["toast", "appearance_audio", "notification"],
    "T-1245": ["appearance", "EVENT_LABELS", "hover_card", "DEFAULT_SOUND_MAP"],
    "T-1244": ["master_mute", "play_result", "queue", "concurrency"],
    "T-1255": ["blip", "wav", "asset", "sha256"],
    "T-1243": ["freebuff", "https", "redirect", "session"],
    "T-1251": ["sound_ref", "resolve_sound_ref", "migrate_sound"],
    "T-1250": ["fail closed", "cache_current_text", "push_sync", "digest"],
    "T-1242": ["fidelity", "QSoundEffect", "loopback", "transient"],
    "T-1249": ["notification", "recovered", "evaluate_limit"],
    "T-1248": ["MARK_PALETTE", "palette", "mark"],
    "T-1247": ["bootstrap_ownership", "no-ACK", "unresponsive", "ownership"],
    "T-1236": ["silo_identity", "remap", "identity"],
    "T-1226": ["quote", "fold", "unquote", "chunk"],
    "T-1205": ["compact", "tooltip", "settings", "empty space"],
}

names = sorted(n for n in os.listdir(TESTS) if n.endswith(".py") and n.startswith("test_"))
blobs = {}
for n in names:
    p = os.path.join(TESTS, n)
    try:
        blobs[n] = io.open(p, encoding="utf-8", errors="replace").read().lower()
    except OSError:
        continue

out = []
for tid, tokens in PROBES.items():
    hits = {}
    for n, body in blobs.items():
        score = sum(1 for t in tokens if t.lower() in body)
        if score:
            hits[n] = score
    ranked = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))
    out.append("{}\t{}".format(tid, ", ".join("{}:{}".format(n, s) for n, s in ranked[:5])))

dest = os.path.join(ROOT, ".saipen", "evidence", "t1350_candidate_tests.txt")
io.open(dest, "w", encoding="utf-8").write("\n".join(out))
print(subprocess.run(["type", dest], shell=True, capture_output=True).stdout.decode("utf-8", "replace"))
