"""Reload package modules and reopen the tool during development."""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for name in tuple(sys.modules):
    if name == "fk_ik_auto_matcher" or name.startswith("fk_ik_auto_matcher."):
        del sys.modules[name]
importlib.invalidate_caches()

from fk_ik_auto_matcher import show

window = show()
