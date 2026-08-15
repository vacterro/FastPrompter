"""Shared test helpers importable from both tests/ and tests_smoke/ at
collection time (root conftest.py puts this directory on sys.path)."""

import os
import tempfile


def junction_ok():
    """Can we create a directory junction/symlink on this machine?"""
    try:
        base = tempfile.mkdtemp()
        target = tempfile.mkdtemp()
        link = os.path.join(base, "j")
        os.symlink(target, link, target_is_directory=True)
        os.rmdir(link)
        os.rmdir(base)
        os.rmdir(target)
        return True
    except (OSError, NotImplementedError):
        return False
