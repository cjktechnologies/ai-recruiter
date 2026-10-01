"""Application configuration (12-factor: everything comes from the environment)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_ENCRYPTION_KEY = "Zm9yLWxvY2FsLWRldi1vbmx5LWNoYW5nZS1tZS0xMjM="  # local/test only; rejected elsewhere


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore", case_sensitive=False)

    # --- Runtime -----------------------------------------------------------
    environment: Literal["local", "test", "staging", "production"] = "local"
    app_name: str = "AI Recruiter"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    public_base_url: str = "http://localhost:3000"

    # --- Data stores -------------------------------------------------------
    database_url: str = "postgresql+psycopg://recruiter:recruiter@localhost:5432/recruiter"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    redis_url: str = "redis://localhost:6379/0"
    # PEM CA bundle for rediss:// (Memorystore in-transit encryption uses a per-instance CA).
    redis_tls_ca_cert: str | None = None

    # --- Security ----------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("change-me-local-only-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "ai-recruiter"
    jwt_audience: str = "ai-recruiter-api"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt PII columns and integration secrets.
    data_encryption_key: SecretStr = SecretStr(DEV_ENCRYPTION_KEY)
    rate_limit_per_minute: int = 300
    auth_rate_limit_per_minute: int = 20
    max_upload_mb: int = 10

    # --- OIDC (optional SSO) -------------------------------------------------
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str | None = None
    oidc_default_org_slug: str | None = None

    # --- Object storage ----------------------------------------------------
    storage_backend: Literal["local", "gcs"] = "local"
    storage_local_path: str = "./var/storage"
    gcp_project_id: str | None = None
    gcs_bucket: str | None = None
    # Optional per-object CMEK (projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>); the bucket's
    # default key applies when unset.
    gcs_kms_key_name: str | None = None

    # --- Malware scanning --------------------------------------------------
    clamav_host: str | None = None
    clamav_port: int = 3310
    require_malware_scan: bool = False

    # --- AI ------------------------------------------------------------------
    llm_provider: Literal["local", "anthropic", "openai", "gemini"] = "local"
    llm_model: str | None = None
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_timeout_seconds: float = 120.0
    llm_max_output_tokens: int = 16000
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 256
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # --- Jobs --------------------------------------------------------------
    task_always_eager: bool = False

    # --- Messaging ---------------------------------------------------------
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    email_from: str = "Recruiting <no-reply@example.com>"
    sms_backend: Literal["console", "twilio"] = "console"
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None

    # --- Governance --------------------------------------------------------
    default_retention_days: int = 730
    consent_validity_days: int = 365

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment in ("staging", "production"):
            secret = self.jwt_secret.get_secret_value()
            if "change-me" in secret or len(secret) < 32:
                raise ValueError("JWT_SECRET must be a strong secret (>=32 chars) outside local/test")
            if self.data_encryption_key.get_secret_value() == DEV_ENCRYPTION_KEY:
                raise ValueError("DATA_ENCRYPTION_KEY must be set outside local/test")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def redis_ssl_options(self) -> dict[str, object]:
        """TLS options for redis-py / Celery when ``REDIS_URL`` uses ``rediss://``.

        The server certificate is verified against the instance CA. Memorystore certificates are
        issued for the instance IP rather than a hostname, so hostname matching is disabled; the
        per-instance CA already pins the peer.
        """
        if not self.redis_url.startswith("rediss://"):
            return {}
        import ssl

        opts: dict[str, object] = {"ssl_cert_reqs": ssl.CERT_REQUIRED, "ssl_check_hostname": False}
        if self.redis_tls_ca_cert:
            opts["ssl_ca_certs"] = self.redis_tls_ca_cert
        return opts


@lru_cache
def get_settings() -> Settings:
    return Settings()
