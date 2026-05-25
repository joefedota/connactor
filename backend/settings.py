from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tmdb_api_read_token: str = ""
    tmdb_api_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "connactorpassword"
    gcs_bucket: str = "connactor-data"
    gcp_project: str = "connactor-497019"

    # Postgres (Neon in prod, local postgres:16 in dev)
    database_url: str = "postgresql+asyncpg://connactor:connactorpassword@localhost:5432/connactor"
    # Used to sign the anonymous user identity cookie
    cookie_secret: str = "dev-cookie-secret-change-in-prod"
    # Set True in prod (Cloud Run is always HTTPS; False lets local HTTP dev work)
    cookie_secure: bool = False

    # Cost + usage report (scripts/cost_report.py)
    billing_dataset: str = "billing_export"
    billing_table: str = "gcp_billing_export_resource_v1_017EE0_4F04E9_9FCF85"
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_zone_tag: str = ""
    resend_api_key: str = ""
    report_recipient: str = "joefedota@gmail.com"
    report_sender: str = "reports@connactor.com"


settings = Settings()
