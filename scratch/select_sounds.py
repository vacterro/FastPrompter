#!/usr/bin/env python3
"""Select and rename best sounds for each category."""

import os
from pathlib import Path

SOUND_DIR = Path(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\sound")

# Best sounds to keep and rename - more inclusive selection
SELECTION = {
    # Currently mapped sounds (MUST keep)
    "mapped": [
        "newbutton1.wav",
        "savebutton1.wav",
        "button1.wav",
        "button2.wav",
        "tickbox1.wav",
        "delete1.wav",
        "clear1.wav",
        "type1.wav",
    ],
    
    # UI Click sounds
    "click": [
        "Click.wav",
        "Mouse click1.wav", 
        "Mouse click2.wav",
        "Buttons 8.wav",
        "Clicks 3.wav",
        "Clicks 6.wav",
    ],
    
    # UI Hover sounds (need to add CS-style)
    "hover": [
        "Pop Up 02.wav",
        "Pop Up 08.wav",
        "Pop Up 09.wav",
        "Pop Up 10.wav",
    ],
    
    # Typewriter sounds
    "type": [
        "type1.wav",
        "type2.wav", 
        "type3.wav",
        "Keyboard one key press.wav",
    ],
    
    # Typewriter backspace
    "backspace": [
        "delete1.wav",  # reuse
    ],
    
    # Notification sounds
    "notify": [
        "bell ding1.wav",
        "notify.wav",
        "notification_alert.wav",
        "NetricsaMessageOpen.wav",
    ],
    
    # Error sounds
    "error": [
        "Error.wav",
    ],
    
    # Success sounds
    "success": [
        "oke....wav",
        "vote_success.wav",
        "trade_success.wav",
    ],
    
    # Chest/Silo sounds
    "chest_open": [
        "chest_open.wav",
        "CHEST.wav",
    ],
    "chest_close": [
        "chest_closed.wav",
    ],
    
    # Timer sounds
    "timer": [
        "det_pack_timer.wav",
        "NEWDAY.wav",
        "NEWWEEK.wav",
        "NEWMONTH.wav",
    ],
    
    # Misc useful sounds
    "misc": [
        "Powerup.wav",
        "Short Whoosh.wav",
        "Short Whoosh2.wav",
        "Move1.wav",
        "DEFAULT.wav",
        "Generic.wav",
    ],
}

def get_other_files():
    """Get files not in selection."""
    selected_files = set()
    for category, files in SELECTION.items():
        selected_files.update(files)
    
    other_files = []
    for f in SOUND_DIR.glob("*.wav"):
        if f.name not in selected_files:
            other_files.append(f.name)
    
    return sorted(other_files)

def calculate_other_size():
    """Calculate total size of 'other' files."""
    other_files = get_other_files()
    total = sum((SOUND_DIR / f).stat().st_size for f in other_files)
    return total

def delete_other_files():
    """Delete files not in selection."""
    other_files = get_other_files()
    
    print(f"Deleting {len(other_files)} unselected files...")
    deleted = 0
    for f in other_files:
        path = SOUND_DIR / f
        try:
            path.unlink()
            deleted += 1
            if deleted % 50 == 0:
                print(f"  Deleted {deleted} files...")
        except Exception as e:
            print(f"  Failed to delete {f}: {e}")
    
    print(f"Deleted {deleted} files")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "delete":
        delete_other_files()
    else:
        print("Selected sounds by category:")
        for cat, files in SELECTION.items():
            print(f"  {cat}: {len(files)}")
            for f in files:
                size = (SOUND_DIR / f).stat().st_size if (SOUND_DIR / f).exists() else 0
                print(f"    - {f} ({size} bytes)")
        
        other_files = get_other_files()
        other_size = calculate_other_size()
        
        print(f"\nOther files (not selected): {len(other_files)}")
        print(f"Total size of other files: {other_size / 1024 / 1024:.2f} MB")
        print(f"\nFirst 20 other files:")
        for f in other_files[:20]:
            size = (SOUND_DIR / f).stat().st_size
            print(f"  {f} ({size} bytes)")
        
        print(f"\nTo delete unselected files, run:")
        print(f"  python scratch/select_sounds.py delete")
