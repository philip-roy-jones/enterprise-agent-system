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
    worker_token: str = os.getenv("EAS_WORKER_TOKEN", "local-worker-demo")
    worker_organization_id: str = os.getenv("EAS_WORKER_ORGANIZATION_ID", "acme")
    worker_role_ids: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("EAS_WORKER_ROLE_IDS", "invoice_correction").split(",")
        if value.strip()
    )
    model_mode: str = os.getenv("EAS_MODEL_MODE", "simulated")
    model_provider: str = os.getenv("EAS_MODEL_PROVIDER", "")
    model_id: str = os.getenv("EAS_MODEL_ID", "")
    desktop_adapter: str = os.getenv("EAS_DESKTOP_ADAPTER", "browser")
    windows_bridge_url: str = os.getenv("EAS_WINDOWS_BRIDGE_URL", "http://127.0.0.1:8765")
    windows_token: str = os.getenv("EAS_WINDOWS_TOKEN", "")
    desktop_agent_url: str = os.getenv("EAS_DESKTOP_AGENT_URL", "http://127.0.0.1:8766")
    desktop_agent_token: str = os.getenv("EAS_DESKTOP_AGENT_TOKEN", "")
    desktop_input_mode: str = os.getenv("EAS_DESKTOP_INPUT_MODE", "accessibility")
    headless: bool = os.getenv("EAS_HEADLESS", "true").lower() == "true"
    max_model_calls: int = int(os.getenv("EAS_MAX_MODEL_CALLS", "12"))
