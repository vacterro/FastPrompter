#!/usr/bin/env python3
"""Sound cleanup script for T-705."""

import os
import subprocess
import shutil
from pathlib import Path

SOUND_DIR = Path(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\sound")
BACKUP_DIR = SOUND_DIR.parent / "sound_backup"

# Target format: 16-bit PCM mono 11.025 kHz WAV (lower for size)
FFMPEG_ARGS = [
    "-ar", "11025",  # sample rate (lower = smaller files)
    "-ac", "1",      # mono
    "-acodec", "pcm_s16le",  # 16-bit PCM little-endian
]

# Current mapping from sound_manager.py
CURRENT_MAP = {
    "new": "newbutton1.wav",
    "save": "savebutton1.wav",
    "silo": "button1.wav",
    "snippet": "button2.wav",
    "tick": "tickbox1.wav",
    "delete": "delete1.wav",
    "clear": "clear1.wav",  # MISSING
    "type": "type1.wav",
    "click": "button1.wav",
}

# Fallbacks
FALLBACKS = {
    "savebutton1.wav": "tickbox3.wav",
    "clear1.wav": "delete1.wav",
    "type1.wav": "tickbox1.wav",
}

def backup_sound_dir():
    """Backup current sound directory."""
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    shutil.copytree(SOUND_DIR, BACKUP_DIR)
    print(f"Backed up to {BACKUP_DIR}")

def convert_to_wav(input_path: Path, output_path: Path) -> bool:
    """Convert audio file to target WAV format using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        *FFMPEG_ARGS,
        str(output_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to convert {input_path.name}: {e.stderr}")
        return False

def get_all_files():
    """Get all audio files with their sizes."""
    files = []
    for ext in ["*.wav", "*.mp3", "*.ogg"]:
        for f in SOUND_DIR.glob(ext):
            files.append((f, f.stat().st_size))
    return sorted(files, key=lambda x: x[1], reverse=True)

def categorize_sound(filename: str) -> str:
    """Categorize sound by purpose based on filename."""
    name_lower = filename.lower()
    
    # UI interactions
    if any(x in name_lower for x in ['click', 'button', 'press', 'tap']):
        return 'ui_click'
    if any(x in name_lower for x in ['hover', 'rollover', 'roll']):
        return 'ui_hover'
    if any(x in name_lower for x in ['tick', 'check', 'box']):
        return 'ui_tick'
    if any(x in name_lower for x in ['delete', 'remove', 'trash']):
        return 'ui_delete'
    if any(x in name_lower for x in ['clear', 'erase']):
        return 'ui_clear'
    if any(x in name_lower for x in ['save', 'store']):
        return 'ui_save'
    if any(x in name_lower for x in ['new', 'add', 'create']):
        return 'ui_new'
    if any(x in name_lower for x in ['popup', 'pop', 'open', 'menu']):
        return 'ui_popup'
    if any(x in name_lower for x in ['close', 'shut']):
        return 'ui_close'
    
    # Typewriter
    if any(x in name_lower for x in ['type', 'key', 'keyboard', 'char']):
        return 'type'
    if any(x in name_lower for x in ['backspace', 'delete', 'erase']):
        return 'backspace'
    
    # Notifications
    if any(x in name_lower for x in ['notify', 'alert', 'message', 'ding', 'bell']):
        return 'notify'
    if any(x in name_lower for x in ['error', 'fail', 'wrong']):
        return 'error'
    if any(x in name_lower for x in ['success', 'complete', 'done', 'ok']):
        return 'success'
    
    # Chest/Silo specific
    if any(x in name_lower for x in ['chest', 'silo', 'container']):
        if 'open' in name_lower:
            return 'chest_open'
        if 'close' in name_lower or 'closed' in name_lower:
            return 'chest_close'
    
    # Timer
    if any(x in name_lower for x in ['timer', 'alarm', 'ring']):
        return 'timer'
    
    return 'other'

def convert_all():
    """Convert all files to target WAV format."""
    backup_sound_dir()
    
    converted = 0
    failed = 0
    
    # Convert MP3/OGG to WAV first
    for ext in ["*.mp3", "*.ogg"]:
        for input_path in SOUND_DIR.glob(ext):
            output_path = SOUND_DIR / f"{input_path.stem}.wav"
            print(f"Converting {input_path.name} to WAV...")
            if convert_to_wav(input_path, output_path):
                converted += 1
                input_path.unlink()
            else:
                failed += 1
    
    # Now re-encode all WAVs to target format
    print("\nRe-encoding all WAVs to target format (11.025 kHz mono 16-bit)...")
    wav_files = list(SOUND_DIR.glob("*.wav"))
    for input_path in wav_files:
        temp_path = SOUND_DIR / f"{input_path.stem}_temp.wav"
        if convert_to_wav(input_path, temp_path):
            input_path.unlink()
            temp_path.rename(input_path)
            converted += 1
        else:
            failed += 1
            if temp_path.exists():
                temp_path.unlink()
    
    print(f"\nTotal operations: {converted}, Failed: {failed}")

def analyze_categories():
    """Analyze current sounds by category."""
    categories = {}
    
    for f in SOUND_DIR.glob("*"):
        if f.is_file():
            cat = categorize_sound(f.name)
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f.name)
    
    print("\nSound categories:")
    for cat, files in sorted(categories.items()):
        print(f"  {cat}: {len(files)} files")
        if len(files) <= 5:
            for f in files:
                print(f"    - {f}")

def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "convert":
        convert_all()
    elif len(sys.argv) > 1 and sys.argv[1] == "categories":
        analyze_categories()
    else:
        print(f"Sound dir: {SOUND_DIR}")
        print(f"Total files: {len(list(SOUND_DIR.glob('*')))}")
        
        # Show largest files
        files = get_all_files()
        print("\nLargest files:")
        for f, size in files[:20]:
            print(f"  {f.name}: {size / 1024:.1f} KB")
        
        # Check which mapped files exist
        print("\nMapped files status:")
        for name, filename in CURRENT_MAP.items():
            path = SOUND_DIR / filename
            exists = path.exists()
            print(f"  {name} -> {filename}: {'OK' if exists else 'MISSING'}")
        
        # Check fallbacks
        print("\nFallback files status:")
        for target, source in FALLBACKS.items():
            target_path = SOUND_DIR / target
            source_path = SOUND_DIR / source
            print(f"  {target} <- {source}: target_exists={target_path.exists()}, source_exists={source_path.exists()}")
        
        print("\nUsage:")
        print("  python scratch/convert_sounds.py convert    - Convert all MP3/OGG to WAV")
        print("  python scratch/convert_sounds.py categories - Analyze by category")

if __name__ == "__main__":
    main()
