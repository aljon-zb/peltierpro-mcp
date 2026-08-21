from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from app.audit import log_tool
from app.branding import branded_response
from app.config import Settings
from app.odoo_client import OdooAPIError, OdooClient
from app.security import clamp_limit, clean_search, positive_id


def register_contacts_tools(
    mcp: FastMCP,
    odoo: OdooClient,
    settings: Settings,
    failed: Callable,
):
    """
    Register read-only Odoo Contacts tools.

    Model:
        res.partner
    """

    # -----------------------------------------------------------------------
    # Search contacts
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def search_contacts(
        search: str = "",
        contact_type: str = "all",
        company_type: str = "all",
        active_only: bool = True,
        limit: int = 20,
    ):
        """
        Search contacts in Odoo Contacts.

        Searches:
        - Name
        - Email
        - Phone
        - Mobile
        - Internal Reference

        contact_type:
        - all
        - contact
        - invoice
        - delivery
        - other
        - private

        company_type:
        - all
        - person
        - company

        Examples:
        - Search for Jenny
        - Find Peltier Pro
        - Show company contacts
        - Show invoice contacts
        """

        params = {
            "search": search,
            "contact_type": contact_type,
            "company_type": company_type,
            "active_only": active_only,
            "limit": limit,
        }

        try:
            search = clean_search(search)
            limit = clamp_limit(
                limit,
                settings.max_results,
            )

            allowed_contact_types = {
                "all",
                "contact",
                "invoice",
                "delivery",
                "other",
                "private",
            }

            allowed_company_types = {
                "all",
                "person",
                "company",
            }

            if contact_type not in allowed_contact_types:
                raise ValueError(
                    "Invalid contact_type. "
                    "Allowed values: "
                    + ", ".join(
                        sorted(
                            allowed_contact_types
                        )
                    )
                )

            if company_type not in allowed_company_types:
                raise ValueError(
                    "Invalid company_type. "
                    "Allowed values: "
                    + ", ".join(
                        sorted(
                            allowed_company_types
                        )
                    )
                )

            domain: list[Any] = []

            if active_only:
                domain.append(
                    (
                        "active",
                        "=",
                        True,
                    )
                )

            if contact_type != "all":
                domain.append(
                    (
                        "type",
                        "=",
                        contact_type,
                    )
                )

            if company_type != "all":
                domain.append(
                    (
                        "company_type",
                        "=",
                        company_type,
                    )
                )

            if search:
                domain += [
                    "|",
                    "|",
                    "|",
                    "|",
                    (
                        "name",
                        "ilike",
                        search,
                    ),
                    (
                        "email",
                        "ilike",
                        search,
                    ),
                    (
                        "phone",
                        "ilike",
                        search,
                    ),
                    (
                        "mobile",
                        "ilike",
                        search,
                    ),
                    (
                        "ref",
                        "ilike",
                        search,
                    ),
                ]

            records = odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "company_type",
                    "is_company",
                    "type",
                    "parent_id",
                    "email",
                    "phone",
                    "mobile",
                    "website",
                    "street",
                    "street2",
                    "city",
                    "state_id",
                    "zip",
                    "country_id",
                    "vat",
                    "ref",
                    "function",
                    "active",
                    "customer_rank",
                    "supplier_rank",
                ],
                limit=limit,
                order="name asc",
            )

            log_tool(
                "search_contacts",
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "count": len(records),
                    "contacts": records,
                }
            )

        except Exception as exc:
            return failed(
                "search_contacts",
                exc,
                params,
            )

    # -----------------------------------------------------------------------
    # Get contact details
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_contact(
        contact_id: int,
    ):
        """
        Get detailed information about a specific Odoo contact.

        Requires the res.partner contact ID.

        Example:
        - Show contact ID 25
        - Get details for contact 103
        """

        params = {
            "contact_id": contact_id,
        }

        try:
            contact_id = positive_id(
                contact_id
            )

            records = odoo.search_read(
                model="res.partner",
                domain=[
                    (
                        "id",
                        "=",
                        contact_id,
                    )
                ],
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "company_type",
                    "is_company",
                    "type",
                    "parent_id",
                    "child_ids",
                    "email",
                    "phone",
                    "mobile",
                    "website",
                    "street",
                    "street2",
                    "city",
                    "state_id",
                    "zip",
                    "country_id",
                    "vat",
                    "ref",
                    "function",
                    "lang",
                    "tz",
                    "active",
                    "customer_rank",
                    "supplier_rank",
                    "category_id",
                    "user_id",
                    "company_id",
                    "create_date",
                    "write_date",
                ],
                limit=1,
            )

            if not records:
                return branded_response(
                    {
                        "success": False,
                        "error": (
                            f"Contact ID "
                            f"{contact_id} "
                            "was not found."
                        ),
                    }
                )

            log_tool(
                "get_contact",
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "contact": records[0],
                }
            )

        except Exception as exc:
            return failed(
                "get_contact",
                exc,
                params,
            )

    # -----------------------------------------------------------------------
    # List customers
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def list_customers(
        search: str = "",
        active_only: bool = True,
        limit: int = 20,
    ):
        """
        List customer contacts.

        Customers are identified using:
            customer_rank > 0

        Examples:
        - Show customers
        - Find customer Peltier
        - List active customers
        """

        params = {
            "search": search,
            "active_only": active_only,
            "limit": limit,
        }

        try:
            search = clean_search(search)
            limit = clamp_limit(
                limit,
                settings.max_results,
            )

            domain: list[Any] = [
                (
                    "customer_rank",
                    ">",
                    0,
                )
            ]

            if active_only:
                domain.append(
                    (
                        "active",
                        "=",
                        True,
                    )
                )

            if search:
                domain += [
                    "|",
                    "|",
                    "|",
                    (
                        "name",
                        "ilike",
                        search,
                    ),
                    (
                        "email",
                        "ilike",
                        search,
                    ),
                    (
                        "phone",
                        "ilike",
                        search,
                    ),
                    (
                        "ref",
                        "ilike",
                        search,
                    ),
                ]

            records = odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "company_type",
                    "parent_id",
                    "email",
                    "phone",
                    "mobile",
                    "website",
                    "city",
                    "state_id",
                    "country_id",
                    "vat",
                    "ref",
                    "function",
                    "customer_rank",
                ],
                limit=limit,
                order="name asc",
            )

            log_tool(
                "list_customers",
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "count": len(records),
                    "customers": records,
                }
            )

        except Exception as exc:
            return failed(
                "list_customers",
                exc,
                params,
            )

    # -----------------------------------------------------------------------
    # List vendors
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def list_vendors(
        search: str = "",
        active_only: bool = True,
        limit: int = 20,
    ):
        """
        List vendor or supplier contacts.

        Vendors are identified using:
            supplier_rank > 0

        Examples:
        - Show vendors
        - List suppliers
        - Find vendor ABC Company
        """

        params = {
            "search": search,
            "active_only": active_only,
            "limit": limit,
        }

        try:
            search = clean_search(search)
            limit = clamp_limit(
                limit,
                settings.max_results,
            )

            domain: list[Any] = [
                (
                    "supplier_rank",
                    ">",
                    0,
                )
            ]

            if active_only:
                domain.append(
                    (
                        "active",
                        "=",
                        True,
                    )
                )

            if search:
                domain += [
                    "|",
                    "|",
                    "|",
                    (
                        "name",
                        "ilike",
                        search,
                    ),
                    (
                        "email",
                        "ilike",
                        search,
                    ),
                    (
                        "phone",
                        "ilike",
                        search,
                    ),
                    (
                        "ref",
                        "ilike",
                        search,
                    ),
                ]

            records = odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "company_type",
                    "parent_id",
                    "email",
                    "phone",
                    "mobile",
                    "website",
                    "city",
                    "state_id",
                    "country_id",
                    "vat",
                    "ref",
                    "function",
                    "supplier_rank",
                ],
                limit=limit,
                order="name asc",
            )

            log_tool(
                "list_vendors",
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "count": len(records),
                    "vendors": records,
                }
            )

        except Exception as exc:
            return failed(
                "list_vendors",
                exc,
                params,
            )

    # -----------------------------------------------------------------------
    # Contacts summary
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def contacts_summary(
        sample_limit: int = 10,
    ):
        """
        Generate a high-level summary of Odoo Contacts.

        Includes:
        - Active contacts
        - Companies
        - Persons
        - Customers
        - Vendors
        - Contacts with email
        - Contacts with phone/mobile
        - Sample recently modified contacts

        Example:
        - Give me a Contacts summary
        - Summarize our customers and vendors
        - How many contacts do we have?
        """

        params = {
            "sample_limit": sample_limit,
        }

        try:
            sample_limit = clamp_limit(
                sample_limit,
                settings.max_results,
            )

            #
            # We deliberately use search_read here
            # instead of requiring search_count()
            # from OdooClient.
            #

            active_contacts = odoo.search_read(
                model="res.partner",
                domain=[
                    (
                        "active",
                        "=",
                        True,
                    )
                ],
                fields=[
                    "id",
                    "company_type",
                    "customer_rank",
                    "supplier_rank",
                    "email",
                    "phone",
                    "mobile",
                ],
                limit=settings.max_results,
            )

            total_active = len(
                active_contacts
            )

            companies = sum(
                1
                for contact in active_contacts
                if contact.get(
                    "company_type"
                )
                == "company"
            )

            persons = sum(
                1
                for contact in active_contacts
                if contact.get(
                    "company_type"
                )
                == "person"
            )

            customers = sum(
                1
                for contact in active_contacts
                if (
                    contact.get(
                        "customer_rank",
                        0,
                    )
                    or 0
                )
                > 0
            )

            vendors = sum(
                1
                for contact in active_contacts
                if (
                    contact.get(
                        "supplier_rank",
                        0,
                    )
                    or 0
                )
                > 0
            )

            with_email = sum(
                1
                for contact in active_contacts
                if contact.get(
                    "email"
                )
            )

            with_phone = sum(
                1
                for contact in active_contacts
                if (
                    contact.get(
                        "phone"
                    )
                    or contact.get(
                        "mobile"
                    )
                )
            )

            recent_contacts = odoo.search_read(
                model="res.partner",
                domain=[
                    (
                        "active",
                        "=",
                        True,
                    )
                ],
                fields=[
                    "id",
                    "name",
                    "company_type",
                    "email",
                    "phone",
                    "mobile",
                    "customer_rank",
                    "supplier_rank",
                    "write_date",
                ],
                limit=sample_limit,
                order="write_date desc",
            )

            log_tool(
                "contacts_summary",
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "summary": {
                        "total_active_contacts": (
                            total_active
                        ),
                        "companies": companies,
                        "persons": persons,
                        "customers": customers,
                        "vendors": vendors,
                        "with_email": with_email,
                        "with_phone_or_mobile": (
                            with_phone
                        ),
                    },
                    "recent_contacts": (
                        recent_contacts
                    ),
                }
            )

        except Exception as exc:
            return failed(
                "contacts_summary",
                exc,
                params,
            )

    # -----------------------------------------------------------------------
    # Company contacts / related contacts
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_company_contacts(
        company_id: int,
        active_only: bool = True,
        limit: int = 50,
    ):
        """
        Show contacts belonging to a company.

        Uses the parent_id relationship in res.partner.

        Examples:
        - Show contacts under Peltier Pro
        - Show people belonging to company ID 15
        """

        params = {
            "company_id": company_id,
            "active_only": active_only,
            "limit": limit,
        }

        try:
            company_id = positive_id(
                company_id
            )

            limit = clamp_limit(
                limit,
                settings.max_results,
            )

            company = odoo.search_read(
                model="res.partner",
                domain=[
                    (
                        "id",
                        "=",
                        company_id,
                    )
                ],
                fields=[
                    "id",
                    "name",
                    "company_type",
                    "is_company",
                ],
                limit=1,
            )

            if not company:
                return branded_response(
                    {
                        "success": False,
                        "error": (
                            f"Company/contact ID "
                            f"{company_id} "
                            "was not found."
                        ),
                    }
                )

            domain: list[Any] = [
                (
                    "parent_id",
                    "=",
                    company_id,
                )
            ]

            if active_only:
                domain.append(
                    (
                        "active",
                        "=",
                        True,
                    )
                )

            contacts = odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "type",
                    "email",
                    "phone",
                    "mobile",
                    "function",
                    "parent_id",
                    "active",
                ],
                limit=limit,
                order="name asc",
            )

            log_tool(
                "get_company_contacts",
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "company": company[0],
                    "count": len(contacts),
                    "contacts": contacts,
                }
            )

        except Exception as exc:
            return failed(
                "get_company_contacts",
                exc,
                params,
            )