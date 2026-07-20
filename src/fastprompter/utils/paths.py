import os
import sys


def _detect_base_dir() -> str:
    """
    Internal: resolve the base directory for bundled assets.

    Priority:
      1. Nuitka onefile temp extraction dir (via __compiled__ + an anchor dir)
      2. Source checkout (go up from src/fastprompter/utils/paths.py)
    """
    if "__compiled__" in globals():
        # Nuitka onefile: bundled data dirs sit alongside the compiled modules
        # in the onefile temp extraction directory. Walk up until we find a
        # parent that has sound/ or _res/ subdir, or hit root.
        candidate = os.path.dirname(os.path.abspath(__file__))
        while True:
            if os.path.isdir(os.path.join(candidate, "sound")) or os.path.isdir(
                os.path.join(candidate, "_res")
            ):
                return candidate
            parent = os.path.dirname(candidate)
            if parent == candidate:  # hit filesystem root
                break
            candidate = parent
        return candidate
    # Running from source: src/fastprompter/utils/paths.py -> project root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


# Cached base dir to avoid repeated filesystem walks
_BASE_DIR = None


def get_base_dir() -> str:
    global _BASE_DIR
    if _BASE_DIR is None:
        _BASE_DIR = _detect_base_dir()
    return _BASE_DIR


def get_exe_dir() -> str:
    """
    Directory containing the executable (for portable DB storage).
    When running from source, returns the project root.
    """
    if "__compiled__" in globals():
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return get_base_dir()


def get_data_dir() -> str:
    """
    Get the directory where user data (like SQLite DB) should be stored.
    Prefers exe-local (portable) over %LOCALAPPDATA%.
    """
    # Portable mode: store DB alongside the executable
    exe_dir = get_exe_dir()
    portable_dir = os.path.join(exe_dir, "data")
    if os.access(exe_dir, os.W_OK):
        os.makedirs(portable_dir, exist_ok=True)
        return portable_dir
    # Fallback to AppData
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        data_dir = os.path.join(local_app_data, "FastPrompter")
    else:
        data_dir = os.path.join(os.path.expanduser("~"), ".fastprompter")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_db_path(profile_id=1) -> str:
    db_name = "local_data_v15.db" if profile_id == 1 else f"local_data_v15_p{profile_id}.db"
    return os.path.join(get_data_dir(), db_name)


def get_portable_backup_dir() -> str:
    home = os.path.expanduser("~")
    documents = os.path.join(home, "Documents")
    base = documents if os.path.isdir(documents) else home
    backup_dir = os.path.join(base, ".fastprompter")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def get_resource_path(*args) -> str:
    """Absolute path to a bundled resource (sounds, fonts, icons)."""
    path = os.path.join(get_base_dir(), *args)
    if os.path.exists(path):
        return path
    # Source layout: some resources (e.g. sound/) live in the package dir
    # (src/fastprompter/) rather than the project root.
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alt = os.path.join(pkg_dir, *args)
    return alt if os.path.exists(alt) else path
