import os
import sys
from pathlib import Path

if sys.platform == "win32":
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    os.environ["PATH"] = str(vendor) + os.pathsep + os.environ["PATH"]

