"""Create local synthetic credentials without printing their values."""

import json
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; it was preserved")
password = secrets.token_hex(24)
partners = {
    secrets.token_hex(24): {
        "tenant_id": "synthetic-partner-a",
        "hmac_secret": secrets.token_hex(32),
    }
}
target.write_text(
    f"GATEWAY_DATABASE_URL=postgresql+psycopg://gateway:{password}@127.0.0.1:54362/credit_gateway\n"
    f"GATEWAY_DB_PASSWORD={password}\n"
    f"GATEWAY_PARTNERS_JSON={json.dumps(partners, separators=(',', ':'))}\n",
    encoding="utf-8",
)
print("Created .env with synthetic local credentials. Values were not printed.")
