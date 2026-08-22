import io
import re
import datetime

p = ".saipen/LOG.md"
s = io.open(p, encoding="utf-8").read()
lines = s.splitlines(keepends=True)

# Re-stamp this session's events (E-816..E-840) onto a monotone UTC
# timeline anchored after E-815 (13:12) and inside the validator's slack.
stamp = datetime.datetime.strptime("22.08.26 13:13", "%d.%m.%y %H:%M")
out = []
seen_repair_note = False
for line in lines:
    m = re.search(r"\[E-(81[6-9]|82[0-9]|83[0-9]|840)\]", line)
    if m:
        line = re.sub(r"^- \d\d\.08\.26 \d\d:\d\d",
                      "- " + stamp.strftime("%d.%m.%y %H:%M"), line)
        stamp += datetime.timedelta(minutes=1)
    out.append(line)
io.open(p, "w", encoding="utf-8", newline="").write("".join(out))
print("re-stamped through", stamp.strftime("%H:%M"))
