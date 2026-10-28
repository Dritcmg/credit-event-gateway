import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Partner:
    tenant_id: str
    hmac_secret: str


@dataclass(frozen=True)
class Settings:
    database_url: str
    partners: dict[str, Partner]
    signature_window: int = 300
    body_limit: int = 65536
    max_attempts: int = 5
    retry_delay: int = 5

    def __post_init__(self):
        if not self.database_url or not self.partners:
            raise ValueError("Database URL and partner credentials must be configured")
        if any(
            len(key) < 16 or len(p.hmac_secret) < 32 or not p.tenant_id
            for key, p in self.partners.items()
        ):
            raise ValueError("Configure non-empty tenants, API keys >=16 and HMAC secrets >=32")
        if not 1 <= self.max_attempts <= 100 or self.retry_delay < 1:
            raise ValueError("Invalid retry configuration")

    @classmethod
    def from_env(cls):
        try:
            credentials = json.loads(os.environ["GATEWAY_PARTNERS_JSON"])
            partners = {key: Partner(**value) for key, value in credentials.items()}
            return cls(os.environ["GATEWAY_DATABASE_URL"], partners)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("Set valid GATEWAY_DATABASE_URL and GATEWAY_PARTNERS_JSON") from error
