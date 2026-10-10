"""Put src/ on the import path, and quiet the HF progress bars.

Imported first by every script, before transformers/sentence-transformers are
loaded, so the environment variables take effect. Set FAIRTRIAL_VERBOSE=1 to
keep the download and weight-loading bars.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if not os.environ.get("FAIRTRIAL_VERBOSE"):
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
