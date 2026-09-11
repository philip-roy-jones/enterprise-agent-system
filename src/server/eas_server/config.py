from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

# Explicit override or launch-directory configuration; never read another app's .env.
load_dotenv(Path(os.getenv("EAS_ENV_FILE", ".env")))


@dataclass
class Settings:
    data_dir: Path = Path(os.getenv("EAS_DATA_DIR", "runtime"))
    backend_url: str = os.getenv("EAS_BACKEND_URL", "http://127.0.0.1:8000")
    bind_host: str = os.getenv("EAS_BIND_HOST", "127.0.0.1")
    bind_port: int = int(os.getenv("EAS_BIND_PORT", "8000"))
    staff_token: str = os.getenv("EAS_STAFF_TOKEN", "local-staff-demo")
    worker_token: str = os.getenv("EAS_WORKER_TOKEN", "local-worker-demo")
    worker_organization_id: str = os.getenv("EAS_WORKER_ORGANIZATION_ID", "acme")
    worker_role_ids: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("EAS_WORKER_ROLE_IDS", "invoice_correction").split(",")
        if value.strip()
    )
    developer_token: str = os.getenv("EAS_DEVELOPER_TOKEN", "local-developer-demo")
    model_mode: str = os.getenv("EAS_MODEL_MODE", "simulated")
    desktop_adapter: str = os.getenv("EAS_DESKTOP_ADAPTER", "browser")
    job_timeout: int = int(os.getenv("EAS_JOB_TIMEOUT_SECONDS", "900"))
