import os
import subprocess
import sys
import shutil

def build_with_nuitka():
    # Ensure we are in the project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(project_root)

    print("Starting Nuitka build for FastPrompter...")

    # Basic Nuitka arguments for a GUI PySide6/PyQt6 app
    # Using PyQt6 based on requirements.txt
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--onefile",
        "--enable-plugin=pyqt6",
        "--windows-disable-console",
        "--output-dir=build",
        "--assume-yes-for-downloads",
        "src/fastprompter/main.py"
    ]

    print("Running command:", " ".join(cmd))
    
    # Run the Nuitka build
    try:
        subprocess.run(cmd, check=True)
        print("\n[SUCCESS] Build complete! Executable is located in the 'build' directory.")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build failed with exit code {e.returncode}")
        sys.exit(e.returncode)

if __name__ == "__main__":
    build_with_nuitka()
