"""Trusted task launcher; keep configuration and logs in this application's directory."""

import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
os.environ["EAS_MEDIATOR_ENV_FILE"] = str(root / "mediator.env")
os.environ["EAS_MEDIATOR_DATA_DIR"] = str(root / "runtime")
(root / "runtime").mkdir(exist_ok=True)
os.chdir(root)
with (root / "runtime" / "service.log").open("a", encoding="utf-8", buffering=1) as log:
    sys.stdout = sys.stderr = log
    from eas_mediator.app import main

    main()
