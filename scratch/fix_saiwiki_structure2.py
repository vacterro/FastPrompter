import os
import shutil
import subprocess
from pathlib import Path

root = Path(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter")
os.chdir(root)

saipen_dir = root / ".saipen"
subs_dir = root / "subs"

# 1. Move subs/saiwiki to .saipen/saiwiki
saiwiki_src = subs_dir / "saiwiki"
saiwiki_dst = saipen_dir / "saiwiki"
if saiwiki_src.exists():
    shutil.move(str(saiwiki_src), str(saiwiki_dst))
    print(f"Moved {saiwiki_src} to {saiwiki_dst}")

# 2. Move subs/MANIFEST.md to .saipen/SUBSAIPEN_MANIFEST.md
manifest_src = subs_dir / "MANIFEST.md"
manifest_dst = saipen_dir / "SUBSAIPEN_MANIFEST.md"
if manifest_src.exists():
    shutil.move(str(manifest_src), str(manifest_dst))
    print(f"Moved {manifest_src} to {manifest_dst}")

# 3. Move subs/RFC_SUBSAIPEN.md to .saipen/RFC_SUBSAIPEN.md
rfc_src = subs_dir / "RFC_SUBSAIPEN.md"
rfc_dst = saipen_dir / "RFC_SUBSAIPEN.md"
if rfc_src.exists():
    shutil.move(str(rfc_src), str(rfc_dst))
    print(f"Moved {rfc_src} to {rfc_dst}")

# 4. Move subs/SUBSAIPEN_PLAN.md to .saipen/SUBSAIPEN_PLAN.md
plan_src = subs_dir / "SUBSAIPEN_PLAN.md"
plan_dst = saipen_dir / "SUBSAIPEN_PLAN.md"
if plan_src.exists():
    shutil.move(str(plan_src), str(plan_dst))
    print(f"Moved {plan_src} to {plan_dst}")

# Clean up empty subs dir
try:
    if subs_dir.exists():
        os.rmdir(subs_dir)
        print("Removed empty subs directory.")
except OSError:
    print("subs directory not empty, leaving it.")

# 5. Delete duplicate wiki files in .saipen/saiwiki/wiki
old_wiki_dir = saipen_dir / "saiwiki" / "wiki"
if old_wiki_dir.exists():
    shutil.rmtree(old_wiki_dir, ignore_errors=True)
    print("Deleted duplicate wiki folder from .saipen/saiwiki/wiki/")

# 6. Update sync_wiki.py to point to docs/wiki/
sync_script = saipen_dir / "saiwiki" / "kitchen" / "sync_wiki.py"
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
