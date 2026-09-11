"""Launch the edge worker without opening a terminal over its assigned desktop."""

from pathlib import Path
import os
import sys

source = Path(__file__).resolve().parents[4]
os.chdir(source)
(source / "runtime").mkdir(exist_ok=True)
with (source / "runtime" / "worker.log").open("a", buffering=1, encoding="utf-8") as output:
    sys.stdout = sys.stderr = output
    from enterprise.cli import main

    sys.argv = ["enterprise", "worker"]
    main()
