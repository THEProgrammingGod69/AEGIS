"""EAGLE EYE engine package.

The engine modules import each other by top-level name (``import config``, ``from kb import drawing_kb``) because the
console, tests and CLIs run from inside ``eagle_eye/``. Importing the package (``python -m eagle_eye.kb.drawing_kb`` from
the repository root) puts this folder on ``sys.path`` so the same imports resolve.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
