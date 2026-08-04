#!/usr/bin/env python3
"""Deduplicate and organize sounds for T-705."""

import os
import hashlib
from pathlib import Path
from collections import defaultdict

SOUND_DIR = Path(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\sound")

def file_hash(path: Path) -> str:
    """Calculate MD5 hash of a file."""
    hasher = hashlib.md5()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def find_duplicates():
    """Find duplicate files by content."""
    hashes = defaultdict(list)
    
    for f in SOUND_DIR.glob("*.wav"):
        h = file_hash(f)
        hashes[h].append(f)
    
    duplicates = {h: files for h, files in hashes.items() if len(files) > 1}
    
    print("Duplicates found:")
    for h, files in duplicates.items():
        print(f"  Hash {h[:8]}:")
        for f in files:
            size = f.stat().st_size
            print(f"    {f.name} ({size} bytes)")
    
    return duplicates

def categorize_by_content():
    """Categorize sounds by analyzing filenames."""
    categories = {
        'click': [],
        'hover': [],
        'type': [],
        'notify': [],
        'error': [],
        'success': [],
        'chest': [],
        'delete': [],
        'save': [],
        'clear': [],
        'other': []
    }
    
    for f in SOUND_DIR.glob("*.wav"):
        name_lower = f.name.lower()
        
        if any(x in name_lower for x in ['click', 'button', 'press']):
            categories['click'].append(f.name)
        elif any(x in name_lower for x in ['hover', 'rollover', 'roll']):
            categories['hover'].append(f.name)
        elif any(x in name_lower for x in ['type', 'key', 'keyboard', 'char']):
            categories['type'].append(f.name)
        elif any(x in name_lower for x in ['notify', 'alert', 'ding', 'bell', 'message']):
            categories['notify'].append(f.name)
        elif any(x in name_lower for x in ['error', 'fail', 'wrong']):
            categories['error'].append(f.name)
        elif any(x in name_lower for x in ['success', 'complete', 'done', 'ok']):
            categories['success'].append(f.name)
        elif any(x in name_lower for x in ['chest', 'silo', 'container']):
            categories['chest'].append(f.name)
        elif any(x in name_lower for x in ['delete', 'remove', 'trash']):
            categories['delete'].append(f.name)
        elif any(x in name_lower for x in ['save', 'store']):
            categories['save'].append(f.name)
        elif any(x in name_lower for x in ['clear', 'erase']):
            categories['clear'].append(f.name)
        else:
            categories['other'].append(f.name)
    
    print("\nCategories:")
    for cat, files in categories.items():
        print(f"  {cat}: {len(files)} files")
        if len(files) <= 10:
            for f in sorted(files):
                print(f"    - {f}")
        else:
            print(f"    (showing first 10 of {len(files)})")
            for f in sorted(files)[:10]:
                print(f"    - {f}")

def show_essential_files():
    """Show files that are currently mapped in sound_manager.py."""
    essential = [
        "newbutton1.wav",
        "savebutton1.wav", 
        "button1.wav",
        "button2.wav",
        "tickbox1.wav",
        "delete1.wav",
        "clear1.wav",
        "type1.wav",
    ]
    
    print("\nEssential mapped files:")
    for f in essential:
        path = SOUND_DIR / f
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        print(f"  {f}: {'OK' if exists else 'MISSING'} ({size} bytes)")

if __name__ == "__main__":
    print(f"Sound dir: {SOUND_DIR}")
    print(f"Total WAV files: {len(list(SOUND_DIR.glob('*.wav')))}")
    
    find_duplicates()
    categorize_by_content()
    show_essential_files()
