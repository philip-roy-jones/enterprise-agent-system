"""Scheduled-task entry point. Planner logs contain no retained private context."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("component", choices=["planner", "executor", "learner"])
parser.add_argument("--env", required=True)
args = parser.parse_args()
os.environ["EAS_ENV_FILE"] = args.env
os.chdir(Path(args.env).parent)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(args.env, override=True)
from eas_harness.config import Settings  # noqa: E402

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
log_path = settings.data_dir / "executor.log" if args.component == "executor" else os.devnull
with open(log_path, "a", buffering=1, encoding="utf-8") as log:
    sys.stdout = sys.stderr = log
    if args.component == "executor":
        from eas_harness.executor import serve

        serve(settings)
    elif args.component == "learner":
        from eas_harness.learner_queue import serve

        serve()
    else:
        from eas_harness.worker import run_worker

        if not settings.executor_url:
            raise RuntimeError("Isolated planner requires the execution broker")
        try:
            run_worker(settings)
        except Exception as error:
            # Retain an operational diagnostic without prompts, credentials,
            # business context, exception messages or tracebacks.
            (settings.data_dir / "planner-exit.json").write_text(
                json.dumps(
                    {"at": datetime.now(timezone.utc).isoformat(), "error_type": type(error).__name__}
                ),
                encoding="utf-8",
            )
            raise
