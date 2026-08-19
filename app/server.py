import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from app.audit import log_tool
from app.branding import branded_response
from app.config import Settings
from app.odoo_client import OdooAPIError, OdooClient
from app.oauth import JWKSJWTTokenVerifier
from mcp.server.transport_security import TransportSecuritySettings
from app.prompts import register_prompts
from app.tools import (
    register_connection_tools,
    register_users_tools,
    register_projects_tools,
    register_crm_tools,
    register_sales_tools,
    register_accounting_tools,
    register_inventory_tools,
)


settings = Settings.from_env()

logging.basicConfig(
    level=getattr(
        logging,
        settings.log_level,
        logging.INFO,
    )
)


# ---------------------------------------------------------------------------
# MCP configuration
# ---------------------------------------------------------------------------

mcp_kwargs: dict[str, Any] = {
    "stateless_http": True,
    "json_response": True,
    "transport_security": TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "peltierpro-mcp-production.up.railway.app",
            "peltierpro-mcp-production.up.railway.app:*",
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
        ],
        allowed_origins=[
            "https://peltierpro-mcp-production.up.railway.app",
            "https://peltierpro-mcp-production.up.railway.app:*",
            "http://localhost:*",
            "http://127.0.0.1:*",
        ],
    ),
}


if settings.auth_enabled:
    mcp_kwargs["token_verifier"] = JWKSJWTTokenVerifier(
        issuer=settings.auth_issuer_url,
        audience=settings.auth_audience,
        jwks_url=settings.auth_jwks_url,
        required_scopes=settings.auth_required_scopes,
        algorithms=settings.auth_algorithms,
    )

    mcp_kwargs["auth"] = AuthSettings(
        issuer_url=AnyHttpUrl(
            settings.auth_issuer_url
        ),
        resource_server_url=AnyHttpUrl(
            settings.auth_resource_server_url
        ),
        required_scopes=settings.auth_required_scopes,
    )


mcp = FastMCP(
    "ZenBiz PeltierPro Odoo MCP",
    **mcp_kwargs,
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@mcp.custom_route(
    "/health",
    methods=["GET"],
)
async def health(request):
    from starlette.responses import JSONResponse

    return JSONResponse(
        {
            "status": "ok",
            "oauth_enabled": settings.auth_enabled,
            "transport": settings.transport,
        }
    )


# ---------------------------------------------------------------------------
# Odoo client
# ---------------------------------------------------------------------------

odoo = OdooClient(
    base_url=settings.odoo_url,
    database=settings.odoo_database,
    api_key=settings.odoo_api_key,
    timeout_seconds=settings.request_timeout_seconds,
)


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def failed(
    tool: str,
    exc: Exception,
    params: dict[str, Any],
):
    log_tool(
        tool,
        params,
        success=False,
        error=str(exc),
    )

    return branded_response(
        {
            "success": False,
            "error": str(exc),
        }
    )


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Register MCP prompts
# ---------------------------------------------------------------------------

register_prompts(mcp)


# ---------------------------------------------------------------------------
# Register MCP tools
# ---------------------------------------------------------------------------

register_connection_tools(mcp, odoo, settings, failed)
register_users_tools(mcp, odoo, settings, failed)
register_projects_tools(mcp, odoo, settings, failed)
register_crm_tools(mcp, odoo, settings, failed)
register_sales_tools(mcp, odoo, settings, failed)
register_accounting_tools(mcp, odoo, settings, failed)
register_inventory_tools(mcp, odoo, settings, failed)


# Start server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if settings.transport == "stdio":
        mcp.run(
            transport="stdio"
        )
    else:
        mcp.settings.host = settings.host
        mcp.settings.port = settings.port

        mcp.run(
            transport="streamable-http"
        )