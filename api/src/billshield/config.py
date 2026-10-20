from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env.local",
        extra="ignore",
        env_ignore_empty=True,
    )

    database_url: SecretStr | None = None
    auth_issuer: str = ""
    auth_audience: str = "authenticated"
    auth_jwks_url: str | None = None
    auth_userinfo_url: str | None = None
    auth_publishable_key: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "ap-south-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket: str = "billshield-uploads"
    upload_ttl_seconds: int = Field(default=120, ge=30, le=300)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = ""
    smtp_starttls: bool = True
    deepseek_api_key: SecretStr | None = None
    law_snapshot_id: str = "m2-auto-ddbfa11807a805fb94ae"
    checks_per_hour: int = Field(default=30, ge=1, le=10000)
