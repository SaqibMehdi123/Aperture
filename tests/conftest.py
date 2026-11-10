import sys
from pathlib import Path

# Allow running pytest from a checkout without installing the packages.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
