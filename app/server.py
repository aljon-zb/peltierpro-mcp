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
# Accounting / Invoice Reporting
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


# ---------------------------------------------------------------------------
# Products
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


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

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