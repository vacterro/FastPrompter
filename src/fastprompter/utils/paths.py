import os
import sys

def get_base_dir() -> str:
    """
    Get the base directory of the application.
    When running via Nuitka, this resolves to the directory containing the executable.
    When running from source, this resolves to the project root.
    """
    if "__compiled__" in globals():
        # Running via Nuitka
        return os.path.dirname(sys.argv[0])
    # Running from source (src/fastprompter/utils/paths.py -> project root)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

def get_data_dir() -> str:
    """
    Get the directory where user data (like SQLite DB) should be stored.
    This resolves to %LOCALAPPDATA%/FastPrompter on Windows to ensure write permissions.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        data_dir = os.path.join(local_app_data, "FastPrompter")
    else:
        # Fallback for non-Windows
        data_dir = os.path.join(os.path.expanduser("~"), ".fastprompter")
        
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def get_db_path(profile_id=1) -> str:
    """
    Get the absolute path to the local SQLite database.
    """
    db_name = "local_data_v15.db" if profile_id == 1 else f"local_data_v15_p{profile_id}.db"
    return os.path.join(get_data_dir(), db_name)

def get_resource_path(*args) -> str:
    """
    Get the absolute path to a bundled resource (e.g. icons, fonts).
    """
    # For Nuitka, --include-data-dir will place assets relative to the executable
    return os.path.join(get_base_dir(), *args)
