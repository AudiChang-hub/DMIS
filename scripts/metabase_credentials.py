"""Shared, environment-only Metabase credentials for maintenance scripts."""

import os


def load_metabase_credentials(*, api: bool = True):
    origin = os.environ.get("METABASE_URL", "http://localhost:3000").rstrip("/")
    if origin.endswith("/api"):
        origin = origin[:-4]
    email = os.environ.get("METABASE_EMAIL")
    password = os.environ.get("METABASE_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "請先設定 METABASE_EMAIL 與 METABASE_PASSWORD 環境變數。"
        )
    base = f"{origin}/api" if api else origin
    return base, email, password
