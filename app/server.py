import logging
from datetime import date, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from app.audit import log_tool
from app.config import Settings
from app.odoo_client import OdooAPIError, OdooClient
from app.oauth import JWKSJWTTokenVerifier
from app.security import (
    ALLOWED_PICKING_STATES,
    ALLOWED_SALES_STATES,
    clamp_limit,
    clean_search,
    positive_id,
    choice,
)
from mcp.server.transport_security import TransportSecuritySettings


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
    "Claude Odoo OAuth Read-Only",
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

    return {
        "success": False,
        "error": str(exc),
    }


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@mcp.tool()
async def test_odoo_connection():
    """
    Verify Odoo JSON-2 authentication without changing data.
    """

    tool = "test_odoo_connection"

    try:
        await odoo.search_read(
            model="res.users",
            domain=[
                ["id", "=", 0],
            ],
            fields=[
                "id",
            ],
            limit=1,
        )

        log_tool(tool)

        return {
            "success": True,
            "message": "Odoo authentication succeeded.",
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            {},
        )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_users(
    search: str = "",
    active_only: bool = True,
    limit: int = 20,
):
    """
    Search Odoo users.

    Read-only.

    Searches by user name or login/email.

    Parameters:
    - search: partial user name or login/email
    - active_only: when true, only active users are returned
    - limit: maximum number of records to return
    """

    tool = "search_users"

    params = {
        "search": clean_search(search),
        "active_only": active_only,
        "limit": limit,
    }

    try:
        safe_limit = clamp_limit(
            limit,
            settings.max_results,
        )

        domain: list[Any] = []

        if active_only:
            domain.append(
                ["active", "=", True]
            )

        if params["search"]:
            domain.extend(
                [
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "login",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="res.users",
            domain=domain,
            fields=[
                "id",
                "name",
                "login",
                "active",
                "partner_id",
                "company_id",
                "company_ids",
                "create_date",
            ],
            limit=safe_limit,
            order="name asc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "users": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


# ---------------------------------------------------------------------------
# Projects / Tasks
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_user_projects_tasks(
    search: str,
    active_only: bool = True,
    limit: int = 20,
):
    """
    Search for Odoo users and return projects that contain tasks
    assigned to the matched user(s).

    Read-only.

    Searches users by name or login/email, then finds project tasks
    where any matched user is included in the task assignees.

    Parameters:
    - search: partial user name or login/email
    - active_only: when true, only active users and active tasks are returned
    - limit: maximum number of task records to return
    """

    tool = "search_user_projects_tasks"

    params = {
        "search": clean_search(search),
        "active_only": active_only,
        "limit": limit,
    }

    try:
        if not params["search"]:
            raise ValueError(
                "Provide a user name or login/email."
            )

        safe_limit = clamp_limit(
            limit,
            settings.max_results,
        )

        user_domain: list[Any] = []

        if active_only:
            user_domain.append(
                ["active", "=", True]
            )

        user_domain.extend(
            [
                "|",
                [
                    "name",
                    "ilike",
                    params["search"],
                ],
                [
                    "login",
                    "ilike",
                    params["search"],
                ],
            ]
        )

        users = await odoo.search_read(
            model="res.users",
            domain=user_domain,
            fields=[
                "id",
                "name",
                "login",
                "active",
            ],
            limit=safe_limit,
            order="name asc",
        )

        if not users:
            log_tool(
                tool,
                params,
                0,
            )

            return {
                "success": True,
                "count": 0,
                "matched_users": [],
                "projects": [],
                "message": "No matching user found.",
            }

        user_ids = [
            user["id"]
            for user in users
        ]

        task_domain: list[Any] = [
            [
                "user_ids",
                "in",
                user_ids,
            ],
            [
                "project_id",
                "!=",
                False,
            ],
        ]

        if active_only:
            task_domain.append(
                ["active", "=", True]
            )

        tasks = await odoo.search_read(
            model="project.task",
            domain=task_domain,
            fields=[
                "id",
                "name",
                "project_id",
                "user_ids",
                "stage_id",
                "date_deadline",
                "priority",
                "create_date",
                "write_date",
            ],
            limit=safe_limit,
            order="project_id asc, id asc",
        )

        projects_by_id: dict[int, dict[str, Any]] = {}

        for task in tasks:
            project = task.get("project_id")

            if not project:
                continue

            project_id = project[0]
            project_name = (
                project[1]
                if len(project) > 1
                else ""
            )

            if project_id not in projects_by_id:
                projects_by_id[project_id] = {
                    "id": project_id,
                    "name": project_name,
                    "task_count": 0,
                    "tasks": [],
                }

            projects_by_id[project_id]["tasks"].append(
                task
            )
            projects_by_id[project_id]["task_count"] += 1

        projects = list(
            projects_by_id.values()
        )

        log_tool(
            tool,
            params,
            len(tasks),
        )

        return {
            "success": True,
            "count": len(projects),
            "task_count": len(tasks),
            "matched_users": users,
            "projects": projects,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


# ---------------------------------------------------------------------------
# CRM
# ---------------------------------------------------------------------------
# Read-only tools:
# - search_crm_opportunities
# - get_crm_opportunity
# - get_crm_pipeline_summary
# - get_crm_opportunities_closing_soon
# - get_stale_crm_opportunities
# - get_crm_salesperson_pipeline
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_crm_opportunities(
    search: str = "",
    limit: int = 20,
):
    """
    Search active CRM opportunities.

    Read-only.
    """

    tool = "search_crm_opportunities"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        domain = [
            ["type", "=", "opportunity"],
            ["active", "=", True],
        ]

        if params["search"]:
            domain.append(
                [
                    "name",
                    "ilike",
                    params["search"],
                ]
            )

        rows = await odoo.search_read(
            model="crm.lead",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "stage_id",
                "expected_revenue",
                "probability",
                "date_deadline",
                "priority",
                "create_date",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="create_date desc, id desc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "opportunities": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_crm_opportunity(
    opportunity_id: int,
):
    """
    Get one CRM opportunity by ID.

    Read-only.
    """

    tool = "get_crm_opportunity"

    params = {
        "opportunity_id": opportunity_id,
    }

    try:
        positive_id(
            opportunity_id,
            "opportunity_id",
        )

        rows = await odoo.read(
            model="crm.lead",
            record_ids=[
                opportunity_id,
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "contact_name",
                "email_from",
                "phone",
                "user_id",
                "team_id",
                "stage_id",
                "expected_revenue",
                "probability",
                "date_deadline",
                "description",
                "create_date",
                "write_date",
            ],
        )

        if not rows:
            raise ValueError(
                "Opportunity not found or access denied."
            )

        log_tool(
            tool,
            params,
            1,
        )

        return {
            "success": True,
            "opportunity": rows[0],
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )



@mcp.tool()
async def get_crm_pipeline_summary(
    limit: int = 100,
):
    """
    Summarize active CRM opportunities by stage.

    Read-only.
    """

    tool = "get_crm_pipeline_summary"
    params = {"limit": limit}

    try:
        rows = await odoo.search_read(
            model="crm.lead",
            domain=[
                ["type", "=", "opportunity"],
                ["active", "=", True],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "stage_id",
                "expected_revenue",
                "probability",
                "date_deadline",
                "priority",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="stage_id asc, id asc",
        )

        by_stage: dict[int, dict[str, Any]] = {}

        for row in rows:
            stage = row.get("stage_id") or [0, "Unspecified"]
            stage_id = stage[0] if stage else 0
            stage_name = stage[1] if stage and len(stage) > 1 else "Unspecified"

            if stage_id not in by_stage:
                by_stage[stage_id] = {
                    "stage_id": stage_id,
                    "stage_name": stage_name,
                    "opportunity_count": 0,
                    "expected_revenue": 0.0,
                }

            by_stage[stage_id]["opportunity_count"] += 1
            by_stage[stage_id]["expected_revenue"] += float(
                row.get("expected_revenue") or 0
            )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "count": len(rows),
            "stages": list(by_stage.values()),
            "opportunities": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_crm_opportunities_closing_soon(
    within_days: int = 7,
    limit: int = 20,
):
    """
    Return active CRM opportunities with deadlines approaching.

    Read-only.
    """

    tool = "get_crm_opportunities_closing_soon"
    params = {
        "within_days": within_days,
        "limit": limit,
    }

    try:
        if within_days < 0:
            raise ValueError("within_days must be 0 or greater.")

        today = date.today()
        until = (today + timedelta(days=within_days)).isoformat()

        rows = await odoo.search_read(
            model="crm.lead",
            domain=[
                ["type", "=", "opportunity"],
                ["active", "=", True],
                ["date_deadline", "!=", False],
                ["date_deadline", ">=", today.isoformat()],
                ["date_deadline", "<=", until],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "stage_id",
                "expected_revenue",
                "probability",
                "date_deadline",
                "priority",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="date_deadline asc, id asc",
        )

        opportunities = []

        for row in rows:
            item = dict(row)
            deadline = row.get("date_deadline")

            if deadline:
                deadline_date = date.fromisoformat(deadline)
                item["days_until_deadline"] = (deadline_date - today).days

            opportunities.append(item)

        log_tool(tool, params, len(opportunities))

        return {
            "success": True,
            "as_of_date": today.isoformat(),
            "within_days": within_days,
            "count": len(opportunities),
            "opportunities": opportunities,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_stale_crm_opportunities(
    inactive_days: int = 30,
    limit: int = 20,
):
    """
    Return active opportunities that have not been updated recently.

    Read-only.
    """

    tool = "get_stale_crm_opportunities"
    params = {
        "inactive_days": inactive_days,
        "limit": limit,
    }

    try:
        if inactive_days < 0:
            raise ValueError("inactive_days must be 0 or greater.")

        cutoff = (date.today() - timedelta(days=inactive_days)).isoformat()

        rows = await odoo.search_read(
            model="crm.lead",
            domain=[
                ["type", "=", "opportunity"],
                ["active", "=", True],
                ["write_date", "<", f"{cutoff} 00:00:00"],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "stage_id",
                "expected_revenue",
                "probability",
                "date_deadline",
                "priority",
                "write_date",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="write_date asc, id asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "inactive_days": inactive_days,
            "count": len(rows),
            "opportunities": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_crm_salesperson_pipeline(
    search: str,
    limit: int = 100,
):
    """
    Return active opportunities assigned to matching salespeople.

    Read-only.
    """

    tool = "get_crm_salesperson_pipeline"
    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        if not params["search"]:
            raise ValueError("Provide a salesperson name or login/email.")

        users = await odoo.search_read(
            model="res.users",
            domain=[
                "|",
                ["name", "ilike", params["search"]],
                ["login", "ilike", params["search"]],
            ],
            fields=[
                "id",
                "name",
                "login",
                "active",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="name asc",
        )

        if not users:
            return {
                "success": True,
                "count": 0,
                "matched_users": [],
                "opportunities": [],
                "message": "No matching salesperson found.",
            }

        user_ids = [user["id"] for user in users]

        rows = await odoo.search_read(
            model="crm.lead",
            domain=[
                ["type", "=", "opportunity"],
                ["active", "=", True],
                ["user_id", "in", user_ids],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "stage_id",
                "expected_revenue",
                "probability",
                "date_deadline",
                "priority",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="user_id asc, stage_id asc, id asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "count": len(rows),
            "matched_users": users,
            "opportunities": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_sales_orders(
    search: str = "",
    state: str = "",
    limit: int = 20,
):
    """
    Search quotations and sales orders.

    Read-only.
    """

    tool = "search_sales_orders"

    params = {
        "search": clean_search(search),
        "state": state,
        "limit": limit,
    }

    try:
        state = choice(
            state,
            ALLOWED_SALES_STATES,
            "sales state",
        )

        domain = []

        if state:
            domain.append(
                [
                    "state",
                    "=",
                    state,
                ]
            )

        if params["search"]:
            domain.extend(
                [
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "partner_id",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="sale.order",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "date_order",
                "commitment_date",
                "state",
                "currency_id",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "invoice_status",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="date_order desc, id desc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "sales_orders": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_sales_order(
    order_id: int,
):
    """
    Get one sales order and its lines.

    Read-only.
    """

    tool = "get_sales_order"

    params = {
        "order_id": order_id,
    }

    try:
        positive_id(
            order_id,
            "order_id",
        )

        orders = await odoo.read(
            model="sale.order",
            record_ids=[
                order_id,
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "date_order",
                "commitment_date",
                "state",
                "currency_id",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "invoice_status",
                "order_line",
            ],
        )

        if not orders:
            raise ValueError(
                "Sales order not found or access denied."
            )

        order = orders[0]

        ids = (
            order.get("order_line") or []
        )[: settings.max_results]

        lines = []

        if ids:
            lines = await odoo.read(
                model="sale.order.line",
                record_ids=ids,
                fields=[
                    "id",
                    "product_id",
                    "name",
                    "product_uom_qty",
                    "qty_delivered",
                    "qty_invoiced",
                    "product_uom",
                    "price_unit",
                    "discount",
                    "price_subtotal",
                    "price_total",
                ],
            )

        log_tool(
            tool,
            params,
            1 + len(lines),
        )

        return {
            "success": True,
            "order": order,
            "lines": lines,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )



# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
# Existing tools:
# - search_sales_orders
# - get_sales_order
#
# Reporting tools:
# - get_sales_summary
# - get_top_customers
# - get_salesperson_performance
# - get_uninvoiced_sales_orders
# - get_expiring_quotations
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_sales_summary(
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
):
    """
    Summarize confirmed sales orders for an optional date range.

    Read-only.

    Parameters:
    - date_from: optional start date in YYYY-MM-DD format
    - date_to: optional end date in YYYY-MM-DD format
    - limit: maximum number of sales orders included in the summary
    """

    tool = "get_sales_summary"

    params = {
        "date_from": clean_search(date_from),
        "date_to": clean_search(date_to),
        "limit": limit,
    }

    try:
        safe_limit = clamp_limit(
            limit,
            settings.max_results,
        )

        domain: list[Any] = [
            ["state", "in", ["sale", "done"]],
        ]

        if params["date_from"]:
            date.fromisoformat(params["date_from"])
            domain.append(
                ["date_order", ">=", f'{params["date_from"]} 00:00:00']
            )

        if params["date_to"]:
            date.fromisoformat(params["date_to"])
            domain.append(
                ["date_order", "<=", f'{params["date_to"]} 23:59:59']
            )

        rows = await odoo.search_read(
            model="sale.order",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "date_order",
                "currency_id",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "invoice_status",
            ],
            limit=safe_limit,
            order="date_order desc, id desc",
        )

        by_currency: dict[int, dict[str, Any]] = {}

        for row in rows:
            currency = row.get("currency_id") or [0, ""]
            currency_id = currency[0] if currency else 0
            currency_name = (
                currency[1]
                if currency and len(currency) > 1
                else ""
            )

            if currency_id not in by_currency:
                by_currency[currency_id] = {
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "order_count": 0,
                    "amount_untaxed": 0.0,
                    "amount_tax": 0.0,
                    "amount_total": 0.0,
                }

            summary = by_currency[currency_id]
            summary["order_count"] += 1
            summary["amount_untaxed"] += float(
                row.get("amount_untaxed") or 0
            )
            summary["amount_tax"] += float(
                row.get("amount_tax") or 0
            )
            summary["amount_total"] += float(
                row.get("amount_total") or 0
            )

        currency_summaries = list(
            by_currency.values()
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "date_from": params["date_from"] or None,
            "date_to": params["date_to"] or None,
            "count": len(rows),
            "currency_summaries": currency_summaries,
            "sales_orders": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_top_customers(
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
):
    """
    Rank customers by confirmed sales order value.

    Read-only.

    Results are separated by currency to avoid mixing totals from
    different currencies.

    Parameters:
    - date_from: optional start date in YYYY-MM-DD format
    - date_to: optional end date in YYYY-MM-DD format
    - limit: maximum number of sales orders used for aggregation
    """

    tool = "get_top_customers"

    params = {
        "date_from": clean_search(date_from),
        "date_to": clean_search(date_to),
        "limit": limit,
    }

    try:
        safe_limit = clamp_limit(
            limit,
            settings.max_results,
        )

        domain: list[Any] = [
            ["state", "in", ["sale", "done"]],
        ]

        if params["date_from"]:
            date.fromisoformat(params["date_from"])
            domain.append(
                ["date_order", ">=", f'{params["date_from"]} 00:00:00']
            )

        if params["date_to"]:
            date.fromisoformat(params["date_to"])
            domain.append(
                ["date_order", "<=", f'{params["date_to"]} 23:59:59']
            )

        rows = await odoo.search_read(
            model="sale.order",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "date_order",
                "currency_id",
                "amount_total",
            ],
            limit=safe_limit,
            order="date_order desc, id desc",
        )

        customers: dict[tuple[int, int], dict[str, Any]] = {}

        for row in rows:
            partner = row.get("partner_id")
            currency = row.get("currency_id")

            if not partner or not currency:
                continue

            partner_id = partner[0]
            partner_name = (
                partner[1]
                if len(partner) > 1
                else ""
            )
            currency_id = currency[0]
            currency_name = (
                currency[1]
                if len(currency) > 1
                else ""
            )

            key = (
                partner_id,
                currency_id,
            )

            if key not in customers:
                customers[key] = {
                    "partner_id": partner_id,
                    "partner_name": partner_name,
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "order_count": 0,
                    "sales_total": 0.0,
                }

            customer = customers[key]
            customer["order_count"] += 1
            customer["sales_total"] += float(
                row.get("amount_total") or 0
            )

        ranked = sorted(
            customers.values(),
            key=lambda item: item["sales_total"],
            reverse=True,
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "date_from": params["date_from"] or None,
            "date_to": params["date_to"] or None,
            "count": len(ranked),
            "customers": ranked,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_salesperson_performance(
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
):
    """
    Summarize confirmed sales by salesperson.

    Read-only.

    Results are separated by salesperson and currency.

    Parameters:
    - date_from: optional start date in YYYY-MM-DD format
    - date_to: optional end date in YYYY-MM-DD format
    - limit: maximum number of sales orders used for aggregation
    """

    tool = "get_salesperson_performance"

    params = {
        "date_from": clean_search(date_from),
        "date_to": clean_search(date_to),
        "limit": limit,
    }

    try:
        safe_limit = clamp_limit(
            limit,
            settings.max_results,
        )

        domain: list[Any] = [
            ["state", "in", ["sale", "done"]],
        ]

        if params["date_from"]:
            date.fromisoformat(params["date_from"])
            domain.append(
                ["date_order", ">=", f'{params["date_from"]} 00:00:00']
            )

        if params["date_to"]:
            date.fromisoformat(params["date_to"])
            domain.append(
                ["date_order", "<=", f'{params["date_to"]} 23:59:59']
            )

        rows = await odoo.search_read(
            model="sale.order",
            domain=domain,
            fields=[
                "id",
                "name",
                "user_id",
                "team_id",
                "date_order",
                "currency_id",
                "amount_total",
            ],
            limit=safe_limit,
            order="date_order desc, id desc",
        )

        performance: dict[tuple[int, int], dict[str, Any]] = {}

        for row in rows:
            user = row.get("user_id")
            currency = row.get("currency_id")

            if not user or not currency:
                continue

            user_id = user[0]
            user_name = (
                user[1]
                if len(user) > 1
                else ""
            )
            currency_id = currency[0]
            currency_name = (
                currency[1]
                if len(currency) > 1
                else ""
            )

            key = (
                user_id,
                currency_id,
            )

            if key not in performance:
                performance[key] = {
                    "user_id": user_id,
                    "user_name": user_name,
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "order_count": 0,
                    "sales_total": 0.0,
                }

            salesperson = performance[key]
            salesperson["order_count"] += 1
            salesperson["sales_total"] += float(
                row.get("amount_total") or 0
            )

        ranked = sorted(
            performance.values(),
            key=lambda item: item["sales_total"],
            reverse=True,
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "date_from": params["date_from"] or None,
            "date_to": params["date_to"] or None,
            "count": len(ranked),
            "salespeople": ranked,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_uninvoiced_sales_orders(
    search: str = "",
    limit: int = 20,
):
    """
    Return confirmed sales orders that still need to be invoiced.

    Read-only.

    Parameters:
    - search: optional sales order or customer search
    - limit: maximum number of records to return
    """

    tool = "get_uninvoiced_sales_orders"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        domain: list[Any] = [
            ["state", "in", ["sale", "done"]],
            ["invoice_status", "=", "to invoice"],
        ]

        if params["search"]:
            domain.extend(
                [
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "partner_id",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="sale.order",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "date_order",
                "commitment_date",
                "currency_id",
                "amount_total",
                "invoice_status",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="date_order asc, id asc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "sales_orders": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_expiring_quotations(
    within_days: int = 7,
    search: str = "",
    limit: int = 20,
):
    """
    Return active quotations whose validity date is approaching.

    Read-only.

    Parameters:
    - within_days: include quotations expiring from today through this many days
    - search: optional quotation or customer search
    - limit: maximum number of records to return
    """

    tool = "get_expiring_quotations"

    params = {
        "within_days": within_days,
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        if within_days < 0:
            raise ValueError(
                "within_days must be 0 or greater."
            )

        today = date.today()
        until = (
            today + timedelta(days=within_days)
        ).isoformat()

        domain: list[Any] = [
            ["state", "in", ["draft", "sent"]],
            ["validity_date", "!=", False],
            ["validity_date", ">=", today.isoformat()],
            ["validity_date", "<=", until],
        ]

        if params["search"]:
            domain.extend(
                [
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "partner_id",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="sale.order",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "user_id",
                "team_id",
                "date_order",
                "validity_date",
                "currency_id",
                "amount_total",
                "state",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="validity_date asc, id asc",
        )

        quotations = []

        for row in rows:
            item = dict(row)
            validity_date = row.get("validity_date")

            if validity_date:
                expiry_date = date.fromisoformat(
                    validity_date
                )
                item["days_until_expiry"] = (
                    expiry_date - today
                ).days

            quotations.append(item)

        log_tool(
            tool,
            params,
            len(quotations),
        )

        return {
            "success": True,
            "as_of_date": today.isoformat(),
            "within_days": within_days,
            "count": len(quotations),
            "quotations": quotations,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------
# Reporting tools:
# - search_customer_invoices_due
# - get_aged_receivables
# - get_aged_payables
# - get_customer_outstanding_balance
# - get_vendor_outstanding_balance
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_customer_invoices_due(
    due_status: str = "overdue",
    due_within_days: int = 7,
    search: str = "",
    limit: int = 20,
):
    """
    Report posted customer invoices that are overdue or almost due.

    Read-only.

    Parameters:
    - due_status: "overdue" or "almost_due"
    - due_within_days: for almost_due, include invoices due from today
      through this many days ahead
    - search: optional customer name or invoice number/reference
    - limit: maximum number of invoice records to return
    """

    tool = "search_customer_invoices_due"

    params = {
        "due_status": clean_search(due_status).lower(),
        "due_within_days": due_within_days,
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        if params["due_status"] not in {
            "overdue",
            "almost_due",
        }:
            raise ValueError(
                'due_status must be "overdue" or "almost_due".'
            )

        if due_within_days < 0:
            raise ValueError(
                "due_within_days must be 0 or greater."
            )

        safe_limit = clamp_limit(
            limit,
            settings.max_results,
        )

        today = date.today()
        today_text = today.isoformat()

        domain: list[Any] = [
            ["move_type", "=", "out_invoice"],
            ["state", "=", "posted"],
            ["payment_state", "not in", ["paid", "reversed"]],
            ["amount_residual", ">", 0],
            ["invoice_date_due", "!=", False],
        ]

        if params["due_status"] == "overdue":
            domain.append(
                ["invoice_date_due", "<", today_text]
            )
        else:
            due_until = (
                today + timedelta(days=due_within_days)
            ).isoformat()

            domain.extend(
                [
                    ["invoice_date_due", ">=", today_text],
                    ["invoice_date_due", "<=", due_until],
                ]
            )

        if params["search"]:
            domain.extend(
                [
                    "|",
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "ref",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "partner_id",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="account.move",
            domain=domain,
            fields=[
                "id",
                "name",
                "ref",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "currency_id",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "amount_residual",
                "payment_state",
                "invoice_payment_term_id",
                "company_id",
            ],
            limit=safe_limit,
            order="invoice_date_due asc, id asc",
        )

        invoices = []

        for row in rows:
            due_date_value = row.get("invoice_date_due")
            days_difference = None

            if due_date_value:
                due_date = date.fromisoformat(
                    due_date_value
                )
                days_difference = (
                    due_date - today
                ).days

            invoice = dict(row)
            invoice["due_status"] = params["due_status"]

            if params["due_status"] == "overdue":
                invoice["days_overdue"] = (
                    abs(days_difference)
                    if days_difference is not None
                    else None
                )
            else:
                invoice["days_until_due"] = (
                    days_difference
                )

            invoices.append(invoice)

        total_residual = sum(
            float(invoice.get("amount_residual") or 0)
            for invoice in invoices
        )

        log_tool(
            tool,
            params,
            len(invoices),
        )

        return {
            "success": True,
            "report": params["due_status"],
            "as_of_date": today_text,
            "due_within_days": (
                due_within_days
                if params["due_status"] == "almost_due"
                else None
            ),
            "count": len(invoices),
            "total_residual": total_residual,
            "invoices": invoices,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )



@mcp.tool()
async def get_aged_receivables(
    search: str = "",
    limit: int = 100,
):
    """
    Return outstanding posted customer invoices grouped into aging buckets.

    Read-only.

    Aging buckets:
    - current
    - 1_30
    - 31_60
    - 61_90
    - 90_plus

    Parameters:
    - search: optional customer name or invoice number/reference
    - limit: maximum number of invoice records to return
    """

    tool = "get_aged_receivables"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        today = date.today()

        domain: list[Any] = [
            ["move_type", "=", "out_invoice"],
            ["state", "=", "posted"],
            ["payment_state", "not in", ["paid", "reversed"]],
            ["amount_residual", ">", 0],
            ["invoice_date_due", "!=", False],
        ]

        if params["search"]:
            domain.extend(
                [
                    "|",
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "ref",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "partner_id",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="account.move",
            domain=domain,
            fields=[
                "id",
                "name",
                "ref",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "currency_id",
                "amount_total",
                "amount_residual",
                "payment_state",
                "company_id",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="invoice_date_due asc, id asc",
        )

        aging_by_currency: dict[int, dict[str, Any]] = {}
        invoices = []

        for row in rows:
            due_value = row.get("invoice_date_due")
            days_overdue = 0

            if due_value:
                due_date = date.fromisoformat(
                    due_value
                )
                days_overdue = max(
                    0,
                    (today - due_date).days,
                )

            if days_overdue == 0:
                bucket = "current"
            elif days_overdue <= 30:
                bucket = "1_30"
            elif days_overdue <= 60:
                bucket = "31_60"
            elif days_overdue <= 90:
                bucket = "61_90"
            else:
                bucket = "90_plus"

            invoice = dict(row)
            invoice["days_overdue"] = days_overdue
            invoice["aging_bucket"] = bucket
            invoices.append(invoice)

            currency = row.get("currency_id") or [0, ""]
            currency_id = currency[0] if currency else 0
            currency_name = (
                currency[1]
                if currency and len(currency) > 1
                else ""
            )

            if currency_id not in aging_by_currency:
                aging_by_currency[currency_id] = {
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "current": 0.0,
                    "1_30": 0.0,
                    "31_60": 0.0,
                    "61_90": 0.0,
                    "90_plus": 0.0,
                    "total_residual": 0.0,
                }

            residual = float(
                row.get("amount_residual") or 0
            )

            aging_by_currency[currency_id][bucket] += residual
            aging_by_currency[currency_id]["total_residual"] += residual

        log_tool(
            tool,
            params,
            len(invoices),
        )

        return {
            "success": True,
            "as_of_date": today.isoformat(),
            "count": len(invoices),
            "aging_by_currency": list(
                aging_by_currency.values()
            ),
            "invoices": invoices,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_aged_payables(
    search: str = "",
    limit: int = 100,
):
    """
    Return outstanding posted vendor bills grouped into aging buckets.

    Read-only.

    Aging buckets:
    - current
    - 1_30
    - 31_60
    - 61_90
    - 90_plus

    Parameters:
    - search: optional vendor name or bill number/reference
    - limit: maximum number of vendor bill records to return
    """

    tool = "get_aged_payables"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        today = date.today()

        domain: list[Any] = [
            ["move_type", "=", "in_invoice"],
            ["state", "=", "posted"],
            ["payment_state", "not in", ["paid", "reversed"]],
            ["amount_residual", ">", 0],
            ["invoice_date_due", "!=", False],
        ]

        if params["search"]:
            domain.extend(
                [
                    "|",
                    "|",
                    [
                        "name",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "ref",
                        "ilike",
                        params["search"],
                    ],
                    [
                        "partner_id",
                        "ilike",
                        params["search"],
                    ],
                ]
            )

        rows = await odoo.search_read(
            model="account.move",
            domain=domain,
            fields=[
                "id",
                "name",
                "ref",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "currency_id",
                "amount_total",
                "amount_residual",
                "payment_state",
                "company_id",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="invoice_date_due asc, id asc",
        )

        aging_by_currency: dict[int, dict[str, Any]] = {}
        bills = []

        for row in rows:
            due_value = row.get("invoice_date_due")
            days_overdue = 0

            if due_value:
                due_date = date.fromisoformat(
                    due_value
                )
                days_overdue = max(
                    0,
                    (today - due_date).days,
                )

            if days_overdue == 0:
                bucket = "current"
            elif days_overdue <= 30:
                bucket = "1_30"
            elif days_overdue <= 60:
                bucket = "31_60"
            elif days_overdue <= 90:
                bucket = "61_90"
            else:
                bucket = "90_plus"

            bill = dict(row)
            bill["days_overdue"] = days_overdue
            bill["aging_bucket"] = bucket
            bills.append(bill)

            currency = row.get("currency_id") or [0, ""]
            currency_id = currency[0] if currency else 0
            currency_name = (
                currency[1]
                if currency and len(currency) > 1
                else ""
            )

            if currency_id not in aging_by_currency:
                aging_by_currency[currency_id] = {
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "current": 0.0,
                    "1_30": 0.0,
                    "31_60": 0.0,
                    "61_90": 0.0,
                    "90_plus": 0.0,
                    "total_residual": 0.0,
                }

            residual = float(
                row.get("amount_residual") or 0
            )

            aging_by_currency[currency_id][bucket] += residual
            aging_by_currency[currency_id]["total_residual"] += residual

        log_tool(
            tool,
            params,
            len(bills),
        )

        return {
            "success": True,
            "as_of_date": today.isoformat(),
            "count": len(bills),
            "aging_by_currency": list(
                aging_by_currency.values()
            ),
            "vendor_bills": bills,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_customer_outstanding_balance(
    search: str,
    limit: int = 100,
):
    """
    Return outstanding posted customer invoices matching a customer.

    Read-only.

    Parameters:
    - search: customer name
    - limit: maximum number of matching invoices to return
    """

    tool = "get_customer_outstanding_balance"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        if not params["search"]:
            raise ValueError(
                "Provide a customer name."
            )

        rows = await odoo.search_read(
            model="account.move",
            domain=[
                ["move_type", "=", "out_invoice"],
                ["state", "=", "posted"],
                ["payment_state", "not in", ["paid", "reversed"]],
                ["amount_residual", ">", 0],
                ["partner_id", "ilike", params["search"]],
            ],
            fields=[
                "id",
                "name",
                "ref",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "currency_id",
                "amount_total",
                "amount_residual",
                "payment_state",
                "company_id",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="invoice_date_due asc, id asc",
        )

        balances: dict[int, dict[str, Any]] = {}

        for row in rows:
            currency = row.get("currency_id") or [0, ""]
            currency_id = currency[0] if currency else 0
            currency_name = (
                currency[1]
                if currency and len(currency) > 1
                else ""
            )

            if currency_id not in balances:
                balances[currency_id] = {
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "outstanding_balance": 0.0,
                }

            balances[currency_id]["outstanding_balance"] += float(
                row.get("amount_residual") or 0
            )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "search": params["search"],
            "count": len(rows),
            "balances_by_currency": list(
                balances.values()
            ),
            "invoices": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_vendor_outstanding_balance(
    search: str,
    limit: int = 100,
):
    """
    Return outstanding posted vendor bills matching a vendor.

    Read-only.

    Parameters:
    - search: vendor name
    - limit: maximum number of matching vendor bills to return
    """

    tool = "get_vendor_outstanding_balance"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        if not params["search"]:
            raise ValueError(
                "Provide a vendor name."
            )

        rows = await odoo.search_read(
            model="account.move",
            domain=[
                ["move_type", "=", "in_invoice"],
                ["state", "=", "posted"],
                ["payment_state", "not in", ["paid", "reversed"]],
                ["amount_residual", ">", 0],
                ["partner_id", "ilike", params["search"]],
            ],
            fields=[
                "id",
                "name",
                "ref",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "currency_id",
                "amount_total",
                "amount_residual",
                "payment_state",
                "company_id",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="invoice_date_due asc, id asc",
        )

        balances: dict[int, dict[str, Any]] = {}

        for row in rows:
            currency = row.get("currency_id") or [0, ""]
            currency_id = currency[0] if currency else 0
            currency_name = (
                currency[1]
                if currency and len(currency) > 1
                else ""
            )

            if currency_id not in balances:
                balances[currency_id] = {
                    "currency_id": currency_id,
                    "currency_name": currency_name,
                    "outstanding_balance": 0.0,
                }

            balances[currency_id]["outstanding_balance"] += float(
                row.get("amount_residual") or 0
            )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "search": params["search"],
            "count": len(rows),
            "balances_by_currency": list(
                balances.values()
            ),
            "vendor_bills": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
# Product and stock tools:
# - search_products
# - get_stock_by_location
# - search_inventory_transfers
#
# Reporting tools:
# - get_low_stock_products
# - get_out_of_stock_products
# - get_inventory_stock_summary
# - get_late_inventory_transfers
# - get_pending_receipts
# - get_pending_deliveries
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_products(
    search: str,
    limit: int = 20,
):
    """
    Search products and product-level stock figures.

    Read-only.
    """

    tool = "search_products"

    params = {
        "search": clean_search(search),
        "limit": limit,
    }

    try:
        if not params["search"]:
            raise ValueError(
                "Provide a product name, reference, or barcode."
            )

        domain = [
            "|",
            "|",
            [
                "name",
                "ilike",
                params["search"],
            ],
            [
                "default_code",
                "ilike",
                params["search"],
            ],
            [
                "barcode",
                "=",
                params["search"],
            ],
        ]

        rows = await odoo.search_read(
            model="product.product",
            domain=domain,
            fields=[
                "id",
                "name",
                "default_code",
                "barcode",
                "type",
                "uom_id",
                "qty_available",
                "virtual_available",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="name asc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "products": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def get_stock_by_location(
    product_id: int,
    limit: int = 50,
):
    """
    Return internal-location stock quants for one product.

    Read-only.
    """

    tool = "get_stock_by_location"

    params = {
        "product_id": product_id,
        "limit": limit,
    }

    try:
        positive_id(
            product_id,
            "product_id",
        )

        rows = await odoo.search_read(
            model="stock.quant",
            domain=[
                [
                    "product_id",
                    "=",
                    product_id,
                ],
                [
                    "location_id.usage",
                    "=",
                    "internal",
                ],
                [
                    "quantity",
                    "!=",
                    0,
                ],
            ],
            fields=[
                "id",
                "product_id",
                "location_id",
                "company_id",
                "quantity",
                "reserved_quantity",
                "available_quantity",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="location_id asc, id asc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "stock_quants": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )


@mcp.tool()
async def search_inventory_transfers(
    reference: str = "",
    state: str = "",
    limit: int = 20,
):
    """
    Search receipts, deliveries, and internal transfers.

    Read-only.
    """

    tool = "search_inventory_transfers"

    params = {
        "reference": clean_search(reference),
        "state": state,
        "limit": limit,
    }

    try:
        state = choice(
            state,
            ALLOWED_PICKING_STATES,
            "transfer state",
        )

        domain = []

        if params["reference"]:
            domain.extend(
                [
                    "|",
                    [
                        "name",
                        "ilike",
                        params["reference"],
                    ],
                    [
                        "origin",
                        "ilike",
                        params["reference"],
                    ],
                ]
            )

        if state:
            domain.append(
                [
                    "state",
                    "=",
                    state,
                ]
            )

        rows = await odoo.search_read(
            model="stock.picking",
            domain=domain,
            fields=[
                "id",
                "name",
                "partner_id",
                "picking_type_id",
                "location_id",
                "location_dest_id",
                "scheduled_date",
                "date_deadline",
                "date_done",
                "state",
                "origin",
                "company_id",
            ],
            limit=clamp_limit(
                limit,
                settings.max_results,
            ),
            order="scheduled_date desc, id desc",
        )

        log_tool(
            tool,
            params,
            len(rows),
        )

        return {
            "success": True,
            "count": len(rows),
            "transfers": rows,
        }

    except Exception as exc:
        return failed(
            tool,
            exc,
            params,
        )



@mcp.tool()
async def get_low_stock_products(
    threshold: float = 10,
    limit: int = 50,
):
    """
    Return products whose available stock is at or below a threshold.

    Read-only.
    """

    tool = "get_low_stock_products"
    params = {
        "threshold": threshold,
        "limit": limit,
    }

    try:
        rows = await odoo.search_read(
            model="product.product",
            domain=[
                ["active", "=", True],
                ["type", "=", "consu"],
                ["qty_available", "<=", threshold],
            ],
            fields=[
                "id",
                "name",
                "default_code",
                "barcode",
                "uom_id",
                "qty_available",
                "virtual_available",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="qty_available asc, name asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "threshold": threshold,
            "count": len(rows),
            "products": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_out_of_stock_products(
    limit: int = 50,
):
    """
    Return active products with no on-hand stock.

    Read-only.
    """

    tool = "get_out_of_stock_products"
    params = {"limit": limit}

    try:
        rows = await odoo.search_read(
            model="product.product",
            domain=[
                ["active", "=", True],
                ["type", "=", "consu"],
                ["qty_available", "<=", 0],
            ],
            fields=[
                "id",
                "name",
                "default_code",
                "barcode",
                "uom_id",
                "qty_available",
                "virtual_available",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="qty_available asc, name asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "count": len(rows),
            "products": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_inventory_stock_summary(
    limit: int = 100,
):
    """
    Return a stock summary for active products.

    Read-only.
    """

    tool = "get_inventory_stock_summary"
    params = {"limit": limit}

    try:
        rows = await odoo.search_read(
            model="product.product",
            domain=[
                ["active", "=", True],
            ],
            fields=[
                "id",
                "name",
                "default_code",
                "type",
                "uom_id",
                "qty_available",
                "virtual_available",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="name asc",
        )

        total_on_hand = sum(
            float(row.get("qty_available") or 0)
            for row in rows
        )
        total_forecast = sum(
            float(row.get("virtual_available") or 0)
            for row in rows
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "count": len(rows),
            "total_on_hand_quantity": total_on_hand,
            "total_forecast_quantity": total_forecast,
            "products": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_late_inventory_transfers(
    limit: int = 50,
):
    """
    Return unfinished inventory transfers whose scheduled date has passed.

    Read-only.
    """

    tool = "get_late_inventory_transfers"
    params = {"limit": limit}

    try:
        today_text = date.today().isoformat()

        rows = await odoo.search_read(
            model="stock.picking",
            domain=[
                ["state", "not in", ["done", "cancel"]],
                ["scheduled_date", "!=", False],
                ["scheduled_date", "<", f"{today_text} 00:00:00"],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "picking_type_id",
                "location_id",
                "location_dest_id",
                "scheduled_date",
                "date_deadline",
                "state",
                "origin",
                "company_id",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="scheduled_date asc, id asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "as_of_date": today_text,
            "count": len(rows),
            "transfers": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_pending_receipts(
    limit: int = 50,
):
    """
    Return unfinished incoming inventory receipts.

    Read-only.
    """

    tool = "get_pending_receipts"
    params = {"limit": limit}

    try:
        rows = await odoo.search_read(
            model="stock.picking",
            domain=[
                ["picking_type_code", "=", "incoming"],
                ["state", "not in", ["done", "cancel"]],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "picking_type_id",
                "scheduled_date",
                "date_deadline",
                "state",
                "origin",
                "company_id",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="scheduled_date asc, id asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "count": len(rows),
            "receipts": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


@mcp.tool()
async def get_pending_deliveries(
    limit: int = 50,
):
    """
    Return unfinished outgoing customer deliveries.

    Read-only.
    """

    tool = "get_pending_deliveries"
    params = {"limit": limit}

    try:
        rows = await odoo.search_read(
            model="stock.picking",
            domain=[
                ["picking_type_code", "=", "outgoing"],
                ["state", "not in", ["done", "cancel"]],
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "picking_type_id",
                "scheduled_date",
                "date_deadline",
                "state",
                "origin",
                "company_id",
            ],
            limit=clamp_limit(limit, settings.max_results),
            order="scheduled_date asc, id asc",
        )

        log_tool(tool, params, len(rows))

        return {
            "success": True,
            "count": len(rows),
            "deliveries": rows,
        }

    except Exception as exc:
        return failed(tool, exc, params)


# ---------------------------------------------------------------------------
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