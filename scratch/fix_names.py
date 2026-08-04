#!/usr/bin/env python3
"""Fix double .wav.wav extensions and clean up sound names."""

import os
import re
from pathlib import Path

SOUND_DIR = Path(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\sound")

def fix_double_extensions():
    """Fix files with .wav.wav extension."""
    fixed = 0
    for f in SOUND_DIR.iterdir():
        if f.is_file() and f.name.endswith(".wav.wav"):
            new_name = f.name[:-4]  # remove last .wav
            new_path = SOUND_DIR / new_name
            print(f"Renaming: {f.name} -> {new_name}")
            f.rename(new_path)
            fixed += 1
    print(f"Fixed {fixed} double extensions")

def clean_filename(name: str) -> str:
    """Clean up filename to lowercase, no spaces, no special chars."""
    # Remove .wav if present
    name = name.replace(".wav", "")
    
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    
    # Remove multiple underscores
    name = re.sub(r"_+", "_", name)
    
    # Remove leading/trailing underscores
    name = name.strip("_")
    
    # Lowercase
    name = name.lower()
    
    return name

def create_rename_map():
    """Create a map of current names to proposed clean names."""
    rename_map = {}
    collisions = {}
    
    for f in SOUND_DIR.glob("*.wav"):
        clean = clean_filename(f.name)
        if clean in rename_map:
            # Collision - add suffix
            if clean not in collisions:
                collisions[clean] = 1
            else:
                collisions[clean] += 1
            clean = f"{clean}_{collisions[clean]}"
        rename_map[f.name] = clean
    
    return rename_map

def show_rename_plan():
    """Show what would be renamed."""
    rename_map = create_rename_map()
    
    print("Rename plan:")
    for old, new in sorted(rename_map.items()):
        if old != new:
            print(f"  {old} -> {new}")
    
    print(f"\nTotal files: {len(rename_map)}")
    print(f"Files to rename: {sum(1 for o, n in rename_map.items() if o != n)}")

def apply_renames():
    """Apply the renames."""
    rename_map = create_rename_map()
    
    renamed = 0
    for old, new in sorted(rename_map.items()):
        if old != new:
            old_path = SOUND_DIR / old
            new_path = SOUND_DIR / new
            print(f"Renaming: {old} -> {new}")
            old_path.rename(new_path)
            renamed += 1
    
    print(f"Renamed {renamed} files")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "fix":
        fix_double_extensions()
    elif len(sys.argv) > 1 and sys.argv[1] == "plan":
        show_rename_plan()
    elif len(sys.argv) > 1 and sys.argv[1] == "apply":
        apply_renames()
    else:
        print("Usage:")
        print("  python scratch/fix_names.py fix   - Fix double .wav.wav extensions")
        print("  python scratch/fix_names.py plan  - Show rename plan")
        print("  python scratch/fix_names.py apply - Apply renames")
