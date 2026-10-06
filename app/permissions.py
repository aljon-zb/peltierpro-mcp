from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import logging
from pathlib import Path
from typing import Any

import yaml
from mcp.server.auth.middleware.auth_context import get_access_token

logger = logging.getLogger("claude_odoo_mcp.permissions")


class PermissionConfigurationError(RuntimeError):
    """Raised when the MCP permission configuration is invalid."""


class PermissionDeniedError(PermissionError):
    """Raised when the authenticated principal cannot use an MCP tool."""


@dataclass(frozen=True)
class Principal:
    key: str
    label: str
    client_id: str | None
    subject: str | None
    email: str | None
    username: str | None


class PermissionManager:
    """
    Config-driven MCP tool authorization.

    Permission patterns use either:
      - "*"                       -> every tool
      - "contacts.*"              -> every Contacts tool
      - "crm.get_crm_opportunity" -> one specific tool
      - "search_users"            -> exact tool name

    The current identity is resolved from the authenticated MCP access token.
    Matching may use sub, email, preferred_username, or client_id.
    """

    def __init__(self, *, enabled: bool, config_file: str) -> None:
        self.enabled = enabled
        self.config_file = Path(config_file)
        self._principals: dict[str, dict[str, Any]] = {}
        self._identifier_index: dict[str, str] = {}
        self._default_permissions: list[str] = []

        if self.enabled:
            self.reload()

    def reload(self) -> None:
        if not self.config_file.exists():
            raise PermissionConfigurationError(
                f"Permission file not found: {self.config_file}"
            )

        with self.config_file.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        principals = raw.get("principals", {})
        defaults = raw.get("defaults", {})

        if not isinstance(principals, dict):
            raise PermissionConfigurationError(
                "permissions.yaml: 'principals' must be a mapping."
            )

        default_permissions = defaults.get("permissions", [])
        if not isinstance(default_permissions, list):
            raise PermissionConfigurationError(
                "permissions.yaml: defaults.permissions must be a list."
            )

        identifier_index: dict[str, str] = {}

        for key, config in principals.items():
            if not isinstance(config, dict):
                raise PermissionConfigurationError(
                    f"permissions.yaml: principal '{key}' must be a mapping."
                )

            identifiers = config.get("identifiers", [])
            permissions = config.get("permissions", [])

            if not isinstance(identifiers, list):
                raise PermissionConfigurationError(
                    f"permissions.yaml: {key}.identifiers must be a list."
                )
            if not isinstance(permissions, list):
                raise PermissionConfigurationError(
                    f"permissions.yaml: {key}.permissions must be a list."
                )

            # The principal key itself is also a valid identifier.
            all_identifiers = [str(key), *[str(item) for item in identifiers]]
            for identifier in all_identifiers:
                normalized = self._normalize_identifier(identifier)
                if normalized:
                    identifier_index[normalized] = str(key)

        self._principals = principals
        self._identifier_index = identifier_index
        self._default_permissions = [str(item) for item in default_permissions]

        logger.info(
            "Loaded MCP permissions from %s (%d principals)",
            self.config_file,
            len(self._principals),
        )

    @staticmethod
    def _normalize_identifier(value: str | None) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _token_claims(token: Any) -> dict[str, Any]:
        claims = getattr(token, "claims", None)
        return claims if isinstance(claims, dict) else {}

    def current_principal(self) -> Principal | None:
        token = get_access_token()
        if token is None:
            return None

        claims = self._token_claims(token)
        subject = getattr(token, "subject", None) or claims.get("sub")
        client_id = getattr(token, "client_id", None)
        email = claims.get("email")
        username = claims.get("preferred_username") or claims.get("username")

        candidates = [subject, email, username, client_id]
        matched_key = None

        for candidate in candidates:
            normalized = self._normalize_identifier(
                str(candidate) if candidate is not None else None
            )
            if normalized and normalized in self._identifier_index:
                matched_key = self._identifier_index[normalized]
                break

        if matched_key is None:
            # Keep a useful identity in logs even when not configured.
            fallback = subject or email or username or client_id or "unknown"
            return Principal(
                key=str(fallback),
                label=str(fallback),
                client_id=str(client_id) if client_id is not None else None,
                subject=str(subject) if subject is not None else None,
                email=str(email) if email is not None else None,
                username=str(username) if username is not None else None,
            )

        config = self._principals.get(matched_key, {})
        return Principal(
            key=matched_key,
            label=str(config.get("label") or matched_key),
            client_id=str(client_id) if client_id is not None else None,
            subject=str(subject) if subject is not None else None,
            email=str(email) if email is not None else None,
            username=str(username) if username is not None else None,
        )

    def _permissions_for_current_principal(self) -> tuple[Principal | None, list[str], bool]:
        principal = self.current_principal()

        if principal is None:
            return None, self._default_permissions, True

        config = self._principals.get(principal.key)
        if config is None:
            return principal, self._default_permissions, True

        enabled = bool(config.get("enabled", True))
        permissions = [str(item) for item in config.get("permissions", [])]
        return principal, permissions, enabled

    @staticmethod
    def permission_key(module: str, tool_name: str) -> str:
        return f"{module}.{tool_name}"

    def is_allowed(self, *, module: str, tool_name: str) -> bool:
        # Local/dev behavior stays unchanged until permissions are explicitly enabled.
        if not self.enabled:
            return True

        _principal, permissions, principal_enabled = (
            self._permissions_for_current_principal()
        )
        if not principal_enabled:
            return False

        full_key = self.permission_key(module, tool_name)

        for pattern in permissions:
            pattern = pattern.strip()
            if not pattern:
                continue

            # Supports "*", "contacts.*", exact full keys, and exact tool names.
            if fnmatch.fnmatchcase(full_key, pattern):
                return True
            if fnmatch.fnmatchcase(tool_name, pattern):
                return True

        return False

    def require(self, *, module: str, tool_name: str) -> None:
        if self.is_allowed(module=module, tool_name=tool_name):
            return

        principal = self.current_principal()
        identity = principal.label if principal else "anonymous"

        raise PermissionDeniedError(
            f"MCP access denied for '{identity}': "
            f"tool '{module}.{tool_name}' is not permitted."
        )

    def identity_for_log(self) -> dict[str, Any]:
        principal = self.current_principal()
        if principal is None:
            return {
                "principal": None,
                "client_id": None,
                "subject": None,
                "email": None,
                "username": None,
            }

        return {
            "principal": principal.label,
            "principal_key": principal.key,
            "client_id": principal.client_id,
            "subject": principal.subject,
            "email": principal.email,
            "username": principal.username,
        }
