import re

with open(r'V:\_TEMP_\opencode\est_full.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

keys = []
for line in lines:
    m = re.match(r'    "(.+?)": "(.+?)",?$', line.strip())
    if m:
        keys.append((m.group(1), line.strip()))

unsorted = False
for i in range(len(keys) - 1):
    if keys[i][0] > keys[i+1][0]:
        print(f"Unsorted at index {i}:")
        print(f"  {keys[i][0][:60]}")
        print(f"  {keys[i+1][0][:60]}")
        print()
        unsorted = True

if not unsorted:
    print("All sorted!")
else:
    print(f"Total keys: {len(keys)}")
