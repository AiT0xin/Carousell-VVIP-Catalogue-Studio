"""Pytest bootstrap: put the repo root on sys.path so `import studio`,
`import qrcheck`, and `import catbuilder` resolve when tests run from anywhere.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
