import importlib.util
import os
import shutil
import subprocess
import sys


def _ensure_nuitka():
    if importlib.util.find_spec("nuitka"):
        return
    print("Nuitka not found. Installing...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "nuitka>=4.1.2"],
        check=True,
    )


def build_with_nuitka():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(project_root)

    _ensure_nuitka()

    print("Starting Nuitka build for FastPrompter...")

    upx_bin = shutil.which("upx")

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "FastPrompter.pyw",
    ]

    if upx_bin:
        cmd.append("--plugin-enable=upx")
        cmd.append(f"--upx-binary={upx_bin}")
        print("UPX compression enabled for smaller executable size.")
    else:
        print("UPX not found. Install UPX (https://upx.github.io/) for 50-60% size reduction.")

    print("Running:", " ".join(cmd))

    # The fastprompter package lives under src/ (the PEP 660 editable
    # install uses an import hook Nuitka can't trace), so put src/ on
    # PYTHONPATH for the compiler — otherwise the app package itself
    # is silently left out of the EXE.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(project_root, "src") + os.pathsep + env.get("PYTHONPATH", "")

    try:
        subprocess.run(cmd, check=True, env=env)
        print("\n[SUCCESS] Build complete! Executable is in 'build' directory.")
        build_dir = os.path.join(project_root, "build")
        if os.path.exists(build_dir):
            for f in os.listdir(build_dir):
                fpath = os.path.join(build_dir, f)
                if os.path.isfile(fpath):
                    size_mb = os.path.getsize(fpath) / (1024 * 1024)
                    print(f"  {f}: {size_mb:.1f} MB")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build failed with exit code {e.returncode}")
        sys.exit(e.returncode)


if __name__ == "__main__":
    build_with_nuitka()
