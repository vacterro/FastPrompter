import sys
import os

# Add src to Python path so it can find fastprompter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fastprompter.main import main_entry

if __name__ == "__main__":
    main_entry()
