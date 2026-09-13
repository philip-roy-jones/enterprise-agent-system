from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv

# Explicit override or launch-directory configuration; never read another app's .env.
load_dotenv(Path(os.getenv("EAS_ENV_FILE", ".env")))


@dataclass
class Settings:
    executor_url: str = os.getenv("EAS_EXECUTOR_URL", "")
    executor_port: int = int(os.getenv("EAS_EXECUTOR_PORT", "8767"))
    admission_token: str = field(default=os.getenv("EAS_ADMISSION_TOKEN", "local-admission-demo"), repr=False)
    data_dir: Path = Path(os.getenv("EAS_DATA_DIR", "runtime"))
    backend_url: str = os.getenv("EAS_BACKEND_URL", "http://127.0.0.1:8000")
    worker_token: str = field(default=os.getenv("EAS_WORKER_TOKEN", "local-worker-demo"), repr=False)
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
    windows_token: str = field(default=os.getenv("EAS_WINDOWS_TOKEN", ""), repr=False)
    desktop_agent_url: str = os.getenv("EAS_DESKTOP_AGENT_URL", "http://127.0.0.1:8766")
    desktop_agent_token: str = field(default=os.getenv("EAS_DESKTOP_AGENT_TOKEN", ""), repr=False)
    desktop_input_mode: str = os.getenv("EAS_DESKTOP_INPUT_MODE", "accessibility")
    campaign_url: str = os.getenv("EAS_CAMPAIGN_URL", "http://127.0.0.1:8770")
    campaign_token: str = field(default=os.getenv("EAS_CAMPAIGN_TOKEN", ""), repr=False)
    headless: bool = os.getenv("EAS_HEADLESS", "true").lower() == "true"
    learning_enabled: bool = os.getenv("EAS_LEARNING_ENABLED", "true").lower() == "true"
    context_max_chars: int = int(os.getenv("EAS_CONTEXT_MAX_CHARS", "96000"))
    max_model_calls: int = int(os.getenv("EAS_MAX_MODEL_CALLS", "12"))
