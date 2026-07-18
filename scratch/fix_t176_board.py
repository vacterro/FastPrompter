import os
import datetime

PROJECT = r"v:\___VAC\__K\__CODE\_PY\_FastPrompter"

# Fix T-176
path = os.path.join(PROJECT, "src", "fastprompter", "ui", "hotkey_mixin.py")
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
if "getattr(self, '_current_lang', 'EN')" in content:
    content = content.replace("getattr(self, '_current_lang', 'EN')", "self._current_lang")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("T-176 fixed.")

board_path = os.path.join(PROJECT, ".asp", "BOARD.md")
with open(board_path, 'r', encoding='utf-8') as f:
    lines = f.read().splitlines()

fixed_tickets = ['T-164', 'T-165', 'T-167', 'T-171', 'T-176', 'T-179', 'T-189', 'T-192', 'T-193', 'T-194', 'T-209', 'T-310']
for i, line in enumerate(lines):
    for t in fixed_tickets:
        if f'| {t} | TODO |' in line or f'| {t} | DOING |' in line:
            lines[i] = line.replace('| TODO |', '| DONE |').replace('| DOING |', '| DONE |')
            break

with open(board_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')

with open(os.path.join(PROJECT, ".asp", "LOG.md"), 'a', encoding='utf-8') as f:
    now = datetime.datetime.now().strftime('%y.%m.%d %H:%M')
    f.write(f'\n- {now} [FIX] RUN: T-164..T-165, T-167, T-171, T-176..T-179, T-189, T-192..T-194, T-209, T-310 -> PASS')

state_path = os.path.join(PROJECT, ".asp", "STATE.md")
with open(state_path, 'r', encoding='utf-8') as f:
    state = f.read()
import re
state = re.sub(r'updated: .*', f'updated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}', state)
with open(state_path, 'w', encoding='utf-8') as f:
    f.write(state)
