"""Read-only probe of Freebuff desktop state.json structure (no secrets printed)."""
import json
from pathlib import Path

p = Path.home() / ".config" / "freebuff-desktop" / "state.json"
data = json.loads(p.read_text(encoding="utf-8"))

SECRET_HINTS = ("token", "secret", "apikey", "api_key", "password", "credential", "authorization")


def redact(v, depth=0):
    if isinstance(v, dict):
        out = {}
        for k, v2 in v.items():
            kl = str(k).lower()
            if any(h in kl for h in SECRET_HINTS) and isinstance(v2, str):
                out[k] = f"<redacted len={len(v2)}>"
            else:
                out[k] = redact(v2, depth + 1)
        return out
    if isinstance(v, list):
        head = [redact(x, depth + 1) for x in v[:5]]
        return head + ([f"...{len(v)} items"] if len(v) > 5 else [])
    if isinstance(v, str) and len(v) > 80:
        return v[:40] + f"...<len={len(v)}>"
    return v


print("TOP KEYS:", sorted(data.keys()))
sessions = data.get("authSessions") or {}
for host, sess in sessions.items():
    print("HOST:", host)
    if isinstance(sess, dict):
        print("  session keys:", sorted(sess.keys()))
        for k in ("user", "userState", "account", "profile"):
            if k in sess:
                print(f"  {k}:", json.dumps(redact(sess[k]), indent=2)[:2000])

for k, v in data.items():
    kl = str(k).lower()
    if any(h in kl for h in ("freebucks", "usage", "credit", "quota", "plan", "balance", "wallet", "price")):
        print("KEY:", k)
        print(json.dumps(redact(v), indent=2)[:3000])

print("=== dir listing ===")
for f in sorted(p.parent.iterdir()):
    print(" ", f.name, f.stat().st_size if f.is_file() else "<dir>")
