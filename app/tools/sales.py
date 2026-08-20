from datetime import date, timedelta
from typing import Any

from app.audit import log_tool
from app.branding import branded_response
from app.security import ALLOWED_SALES_STATES, clamp_limit, clean_search, positive_id, choice


def register_sales_tools(mcp, odoo, settings, failed):
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
        
        Provider: Zen Business Solutions
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

            return branded_response(
                {
                    "success": True,
                    "count": len(rows),
                    "sales_orders": rows,
                }
            )

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
        
        Provider: Zen Business Solutions
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

            return branded_response(
                {
                    "success": True,
                    "order": order,
                    "lines": lines,
                }
            )

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
        
        Provider: Zen Business Solutions

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

            return branded_response(
                {
                    "success": True,
                    "date_from": params["date_from"] or None,
                    "date_to": params["date_to"] or None,
                    "count": len(rows),
                    "currency_summaries": currency_summaries,
                    "sales_orders": rows,
                }
            )

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
        
        Provider: Zen Business Solutions

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

            return branded_response(
                {
                    "success": True,
                    "date_from": params["date_from"] or None,
                    "date_to": params["date_to"] or None,
                    "count": len(ranked),
                    "customers": ranked,
                }
            )

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
        
        Provider: Zen Business Solutions

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

            return branded_response(
                {
                    "success": True,
                    "date_from": params["date_from"] or None,
                    "date_to": params["date_to"] or None,
                    "count": len(ranked),
                    "salespeople": ranked,
                }
            )

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
        
        Provider: Zen Business Solutions

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

            return branded_response(
                {
                    "success": True,
                    "count": len(rows),
                    "sales_orders": rows,
                }
            )

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
        
        Provider: Zen Business Solutions

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

            return branded_response(
                {
                    "success": True,
                    "as_of_date": today.isoformat(),
                    "within_days": within_days,
                    "count": len(quotations),
                    "quotations": quotations,
                }
            )

        except Exception as exc:
            return failed(
                tool,
                exc,
                params,
            )


    # ---------------------------------------------------------------------------
