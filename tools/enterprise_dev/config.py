from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv
from eas_server.config import Settings as ServerSettings

repository = Path(__file__).resolve().parents[2]
load_dotenv((repository if (repository / "pyproject.toml").is_file() else Path.cwd()) / ".env")


@dataclass
class Settings(ServerSettings):
    executor_url: str = os.getenv("EAS_EXECUTOR_URL", "")
    executor_port: int = int(os.getenv("EAS_EXECUTOR_PORT", "8767"))
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
    model_provider: str = os.getenv("EAS_MODEL_PROVIDER", "")
    model_id: str = os.getenv("EAS_MODEL_ID", "")
    desktop_adapter: str = os.getenv("EAS_DESKTOP_ADAPTER", "browser")
    windows_bridge_url: str = os.getenv("EAS_WINDOWS_BRIDGE_URL", "http://127.0.0.1:8765")
    windows_token: str = field(default=os.getenv("EAS_WINDOWS_TOKEN", ""), repr=False)
    desktop_agent_url: str = os.getenv("EAS_DESKTOP_AGENT_URL", "http://127.0.0.1:8766")
    desktop_agent_token: str = field(default=os.getenv("EAS_DESKTOP_AGENT_TOKEN", ""), repr=False)
    desktop_input_mode: str = os.getenv("EAS_DESKTOP_INPUT_MODE", "accessibility")
    headless: bool = os.getenv("EAS_HEADLESS", "true").lower() == "true"
    job_timeout: int = int(os.getenv("EAS_JOB_TIMEOUT_SECONDS", "900"))
    learning_enabled: bool = os.getenv("EAS_LEARNING_ENABLED", "true").lower() == "true"
    max_model_calls: int = int(os.getenv("EAS_MAX_MODEL_CALLS", "12"))
