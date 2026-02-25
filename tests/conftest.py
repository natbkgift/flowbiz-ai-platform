from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

# Avoid collisions with any preloaded `apps` package from other repos/environments.
apps_mod = sys.modules.get("apps")
if apps_mod is not None:
    mod_file = str(getattr(apps_mod, "__file__", ""))
    if root_str not in mod_file:
        sys.modules.pop("apps", None)
