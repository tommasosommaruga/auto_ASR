"""Download the speaker models once. Speech models download on first use."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import ensure_diarization_models

if __name__ == "__main__":
    ensure_diarization_models()
    print("Speaker models are on this computer.")
