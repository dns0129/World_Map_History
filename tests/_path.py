"""Put scripts/ on the import path (the scripts import each other by module name)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
