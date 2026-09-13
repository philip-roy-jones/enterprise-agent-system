from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv

# Explicit override or launch-directory configuration; never read another app's .env.
load_dotenv(Path(os.getenv("EAS_ENV_FILE", ".env")))


@dataclass
class Settings:
    auth_mode: str = os.getenv("EAS_AUTH_MODE", "development")
    identity_file: str = os.getenv("EAS_IDENTITY_FILE", "")
    public_url: str = os.getenv("EAS_PUBLIC_URL", "http://127.0.0.1:8000")
    admission_token: str = field(default=os.getenv("EAS_ADMISSION_TOKEN", "local-admission-demo"), repr=False)
    planner_token: str = field(default=os.getenv("EAS_PLANNER_TOKEN", "local-planner-demo"), repr=False)
    data_dir: Path = Path(os.getenv("EAS_DATA_DIR", "runtime"))
    backend_url: str = os.getenv("EAS_BACKEND_URL", "http://127.0.0.1:8000")
    bind_host: str = os.getenv("EAS_BIND_HOST", "127.0.0.1")
    bind_port: int = int(os.getenv("EAS_BIND_PORT", "8000"))
    staff_token: str = field(default=os.getenv("EAS_STAFF_TOKEN", "local-staff-demo"), repr=False)
    worker_token: str = field(default=os.getenv("EAS_WORKER_TOKEN", "local-worker-demo"), repr=False)
    worker_organization_id: str = os.getenv("EAS_WORKER_ORGANIZATION_ID", "acme")
    worker_role_ids: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("EAS_WORKER_ROLE_IDS", "invoice_correction").split(",")
        if value.strip()
    )
    developer_token: str = field(default=os.getenv("EAS_DEVELOPER_TOKEN", "local-developer-demo"), repr=False)
    model_mode: str = os.getenv("EAS_MODEL_MODE", "simulated")
    desktop_adapter: str = os.getenv("EAS_DESKTOP_ADAPTER", "none")
    job_timeout: int = int(os.getenv("EAS_JOB_TIMEOUT_SECONDS", "900"))
