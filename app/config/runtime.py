from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config.workbook_schema import PROJECT_ROOT


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class RuntimeConfig:
    dvsa_client_id: str
    dvsa_client_secret: str
    dvsa_api_key: str
    dvsa_scope: str
    dvsa_token_url: str
    dvsa_api_base_url: str
    dvsa_registration_paths: tuple[str, ...]
    google_maps_api_key: str

    @property
    def dvsa_enabled(self) -> bool:
        return bool(
            self.dvsa_client_id
            and self.dvsa_client_secret
            and self.dvsa_api_key
            and self.dvsa_scope
            and self.dvsa_token_url
        )

    @property
    def google_maps_enabled(self) -> bool:
        return bool(self.google_maps_api_key)


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    _load_dotenv(PROJECT_ROOT / ".env")

    raw_paths = os.getenv(
        "DVSA_REGISTRATION_PATHS",
        "/v1/trade/vehicles/registration/{registration},"
        "/v1/trade/vehicles/registration?registration={registration},"
        "/v1/trade/vehicles/registration?vrm={registration}",
    )
    registration_paths = tuple(
        segment.strip() for segment in raw_paths.split(",") if segment.strip()
    )

    return RuntimeConfig(
        dvsa_client_id=os.getenv("DVSA_CLIENT_ID", "").strip(),
        dvsa_client_secret=os.getenv("DVSA_CLIENT_SECRET", "").strip(),
        dvsa_api_key=os.getenv("DVSA_API_KEY", "").strip(),
        dvsa_scope=os.getenv("DVSA_SCOPE", "https://tapi.dvsa.gov.uk/.default").strip(),
        dvsa_token_url=os.getenv(
            "DVSA_TOKEN_URL",
            "https://login.microsoftonline.com/a455b827-244f-4c97-b5b4-ce5d13b4d00c/oauth2/v2.0/token",
        ).strip(),
        dvsa_api_base_url=os.getenv(
            "DVSA_API_BASE_URL", "https://history.mot.api.gov.uk"
        ).strip(),
        dvsa_registration_paths=registration_paths,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", "").strip(),
    )


def public_frontend_config() -> dict[str, object]:
    config = get_runtime_config()
    return {
        "dvsa": {"enabled": config.dvsa_enabled},
        "google_maps": {
            "enabled": config.google_maps_enabled,
            "api_key": config.google_maps_api_key,
        },
        "features": {
            "autotrader_enabled": False,
            "instagram_mode": "prototype",
            "barclays_enabled": False,
        },
    }
