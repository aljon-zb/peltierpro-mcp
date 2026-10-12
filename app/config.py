from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _csv(name: str, default: str = "") -> list[str]:
    return [
        value.strip()
        for value in os.getenv(name, default).split(",")
        if value.strip()
    ]


def _bool(name: str, default: str = "false") -> bool:
    return (
        os.getenv(name, default).strip().lower()
        in {"1", "true", "yes", "on"}
    )


def _positive_int(name: str, default: str) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _is_secure_http_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "https":
        return True
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_database: str
    odoo_api_key: str

    transport: str
    host: str
    port: int
    request_timeout_seconds: float
    max_results: int
    log_level: str

    auth_enabled: bool
    auth_resource_server_url: str | None
    auth_required_scopes: list[str]
    auth_access_token_ttl_seconds: int
    auth_refresh_token_ttl_seconds: int
    auth_code_ttl_seconds: int

    permissions_enabled: bool
    permissions_file: str

    @classmethod
    def from_env(cls) -> "Settings":
        required = (
            "ODOO_URL",
            "ODOO_DATABASE",
            "ODOO_API_KEY",
        )

        missing = [
            name
            for name in required
            if not os.getenv(name)
        ]

        if missing:
            raise ConfigurationError(
                "Missing required environment variable(s): "
                + ", ".join(missing)
            )

        transport = os.getenv(
            "TRANSPORT",
            "stdio",
        ).strip().lower()

        if transport not in {
            "stdio",
            "streamable-http",
        }:
            raise ConfigurationError(
                "TRANSPORT must be 'stdio' or 'streamable-http'."
            )

        port = int(os.getenv("PORT", "8000"))
        max_results = int(os.getenv("MAX_RESULTS", "50"))
        timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

        if not 1 <= port <= 65535:
            raise ConfigurationError(
                "PORT must be between 1 and 65535."
            )

        if not 1 <= max_results <= 200:
            raise ConfigurationError(
                "MAX_RESULTS must be between 1 and 200."
            )

        # --------------------------------------------------
        # Authentication
        # --------------------------------------------------

        auth_enabled = _bool("AUTH_ENABLED")
        resource = (
            os.getenv("AUTH_RESOURCE_SERVER_URL", "").strip()
            or None
        )
        scopes = _csv("AUTH_REQUIRED_SCOPES", "odoo.read")
        auth_access_token_ttl_seconds = _positive_int(
            "AUTH_ACCESS_TOKEN_TTL_SECONDS",
            "3600",
        )
        auth_refresh_token_ttl_seconds = _positive_int(
            "AUTH_REFRESH_TOKEN_TTL_SECONDS",
            "2592000",
        )
        auth_code_ttl_seconds = _positive_int(
            "AUTH_CODE_TTL_SECONDS",
            "300",
        )

        if auth_enabled:
            oauth_missing = []
            if not resource:
                oauth_missing.append("AUTH_RESOURCE_SERVER_URL")
            if not scopes:
                oauth_missing.append("AUTH_REQUIRED_SCOPES")

            if oauth_missing:
                raise ConfigurationError(
                    "AUTH_ENABLED=true but missing: "
                    + ", ".join(oauth_missing)
                )

            if resource and not _is_secure_http_url(resource):
                raise ConfigurationError(
                    "AUTH_RESOURCE_SERVER_URL must use HTTPS "
                    "(HTTP is allowed only for localhost development)."
                )

        # --------------------------------------------------
        # Permissions
        # --------------------------------------------------

        permissions_enabled = _bool("PERMISSIONS_ENABLED")
        permissions_file = os.getenv(
            "PERMISSIONS_FILE",
            "config/permissions.yaml",
        ).strip()

        if permissions_enabled and not auth_enabled:
            raise ConfigurationError(
                "PERMISSIONS_ENABLED=true requires "
                "AUTH_ENABLED=true so the server can "
                "identify the caller securely."
            )

        if permissions_enabled and not permissions_file:
            raise ConfigurationError(
                "PERMISSIONS_FILE cannot be blank "
                "when permissions are enabled."
            )

        return cls(
            odoo_url=os.environ["ODOO_URL"].rstrip("/"),
            odoo_database=os.environ["ODOO_DATABASE"].strip(),
            odoo_api_key=os.environ["ODOO_API_KEY"].strip(),
            transport=transport,
            host=os.getenv("HOST", "127.0.0.1").strip(),
            port=port,
            request_timeout_seconds=timeout,
            max_results=max_results,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            auth_enabled=auth_enabled,
            auth_resource_server_url=resource,
            auth_required_scopes=scopes,
            auth_access_token_ttl_seconds=auth_access_token_ttl_seconds,
            auth_refresh_token_ttl_seconds=auth_refresh_token_ttl_seconds,
            auth_code_ttl_seconds=auth_code_ttl_seconds,
            permissions_enabled=permissions_enabled,
            permissions_file=permissions_file,
        )
