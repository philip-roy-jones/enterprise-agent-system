from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass
class Settings:
    data_dir: Path = Path(os.getenv("EAS_DATA_DIR", "runtime"))
    backend_url: str = os.getenv("EAS_BACKEND_URL", "http://127.0.0.1:8000")
    staff_token: str = os.getenv("EAS_STAFF_TOKEN", "local-staff-demo")
    worker_token: str = os.getenv("EAS_WORKER_TOKEN", "local-worker-demo")
    developer_token: str = os.getenv("EAS_DEVELOPER_TOKEN", "local-developer-demo")
    model_mode: str = os.getenv("EAS_MODEL_MODE", "simulated")
    model_provider: str = os.getenv("EAS_MODEL_PROVIDER", "")
    model_id: str = os.getenv("EAS_MODEL_ID", "")
    desktop_adapter: str = os.getenv("EAS_DESKTOP_ADAPTER", "browser")
    windows_bridge_url: str = os.getenv("EAS_WINDOWS_BRIDGE_URL", "http://127.0.0.1:8765")
    windows_token: str = os.getenv("EAS_WINDOWS_TOKEN", "")
    headless: bool = os.getenv("EAS_HEADLESS", "true").lower() == "true"
    job_timeout: int = int(os.getenv("EAS_JOB_TIMEOUT_SECONDS", "900"))
    max_model_calls: int = int(os.getenv("EAS_MAX_MODEL_CALLS", "12"))
