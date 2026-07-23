import os
import shutil
import subprocess
from pathlib import Path

def run_cmd(cmd):
    print(f"Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.returncode != 0:
        print(f"Error: {res.stderr}")
    else:
        print(res.stdout)

root = Path(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter")
os.chdir(root)

# 1. Move subs/saiwiki to .saipen/saiwiki
if not (root / ".saipen" / "saiwiki").exists():
    run_cmd(["git", "mv", "subs/saiwiki", ".saipen/saiwiki"])

# 2. Move subs/MANIFEST.md to .saipen/
if (root / "subs" / "MANIFEST.md").exists():
    run_cmd(["git", "mv", "subs/MANIFEST.md", ".saipen/SUBSAIPEN_MANIFEST.md"])

# 3. Move subs/RFC_SUBSAIPEN.md to .saipen/ (if exists)
if (root / "subs" / "RFC_SUBSAIPEN.md").exists():
    run_cmd(["git", "mv", "subs/RFC_SUBSAIPEN.md", ".saipen/RFC_SUBSAIPEN.md"])

# 4. Remove subs directory if empty or move any remaining files
if (root / "subs" / "SUBSAIPEN_PLAN.md").exists():
    run_cmd(["git", "mv", "subs/SUBSAIPEN_PLAN.md", ".saipen/SUBSAIPEN_PLAN.md"])

try:
    if (root / "subs").exists():
        os.rmdir(root / "subs")
        print("Removed empty subs directory.")
except OSError:
    print("subs directory not empty, leaving it.")

# 5. Delete the duplicate wiki files in .saipen/saiwiki/wiki
# Since docs/wiki/ is the source of truth, we don't need this duplicate
old_wiki_dir = root / ".saipen" / "saiwiki" / "wiki"
if old_wiki_dir.exists():
    run_cmd(["git", "rm", "-r", ".saipen/saiwiki/wiki"])
    if old_wiki_dir.exists():
        shutil.rmtree(old_wiki_dir, ignore_errors=True)
    print("Deleted duplicate wiki folder from .saipen/saiwiki/wiki/")

# 6. Update sync_wiki.py to point to docs/wiki/
sync_script = root / ".saipen" / "saiwiki" / "kitchen" / "sync_wiki.py"
if sync_script.exists():
    with open(sync_script, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Change DEFAULT_WIKI_DIR pointing
    content = content.replace(
        'DEFAULT_WIKI_DIR = SAIWIKI_ROOT / "wiki"',
        'DEFAULT_WIKI_DIR = SAIWIKI_ROOT.parent.parent / "docs" / "wiki"'
    )
    
    with open(sync_script, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated sync_wiki.py to use docs/wiki/")
