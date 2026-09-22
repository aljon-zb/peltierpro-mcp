from html import escape
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
    Register Odoo Contacts tools.

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
        is_company: bool | None = None,
        active_only: bool = True,
        limit: int = 20,
    ):
        """
        Search contacts in Odoo Contacts.

        Searches:
        - Name
        - Email
        - Phone
        - Internal Reference

        contact_type:
        - all
        - contact
        - invoice
        - delivery
        - other
        - private

        is_company:
        - None = all contacts
        - True = company
        - False = person

        Examples:
        - Search for Jenny
        - Find Peltier Pro
        - Show company contacts
        - Show invoice contacts
        """

        params = {
            "search": search,
            "contact_type": contact_type,
            "is_company": is_company,
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

            if is_company is not None:
                domain.append(
                    (
                        "is_company",
                        "=",
                        is_company,
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

            records = await odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "is_company",
                    "type",
                    "parent_id",
                    "email",
                    "phone",
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

            records = await odoo.search_read(
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
                    "is_company",
                    "type",
                    "parent_id",
                    "child_ids",
                    "email",
                    "phone",
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

            records = await odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "parent_id",
                    "email",
                    "phone",
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

            records = await odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "parent_id",
                    "email",
                    "phone",
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
        - Contacts with phone
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

            active_contacts = await odoo.search_read(
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
                    "is_company",
                    "customer_rank",
                    "supplier_rank",
                    "email",
                    "phone",
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
                    "is_company"
                )
                is True
            )

            persons = sum(
                1
                for contact in active_contacts
                if contact.get(
                    "is_company"
                )
                is False
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
                if contact.get(
                    "phone"
                )
            )

            recent_contacts = await odoo.search_read(
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
                    "email",
                    "phone",
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
                        "with_phone": (
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

            company = await odoo.search_read(
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

            contacts = await odoo.search_read(
                model="res.partner",
                domain=domain,
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "type",
                    "email",
                    "phone",
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

    # -----------------------------------------------------------------------
    # Create company with person contacts
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def create_company_contacts(
        company_name: str,
        contact_names: list[str],
    ):
        """
        Create a company contact if it does not already exist, then create
        person contacts under that company.

        Existing company/person contacts are reused instead of duplicated.

        Example:
        - Create company "MCP Test" if it does not exist, then create:
          Test MCP User 1
          Test MCP User 2
          Test MCP User 3
          Test MCP User 4
          Test MCP User 5

        Provider: Zen Business Solutions
        """

        tool = "create_company_contacts"

        params = {
            "company_name": company_name,
            "contact_names": contact_names,
        }

        try:
            company_name = clean_search(company_name)

            if not company_name:
                raise ValueError(
                    "company_name is required."
                )

            if not contact_names:
                raise ValueError(
                    "At least one contact name is required."
                )

            if len(contact_names) > settings.max_results:
                raise ValueError(
                    f"Too many contacts. Maximum allowed is {settings.max_results}."
                )

            cleaned_contact_names = []

            for index, contact_name in enumerate(
                contact_names,
                start=1,
            ):
                cleaned_name = clean_search(contact_name)

                if not cleaned_name:
                    raise ValueError(
                        f"contact_names[{index}] cannot be empty."
                    )

                if cleaned_name not in cleaned_contact_names:
                    cleaned_contact_names.append(cleaned_name)

            companies = await odoo.search_read(
                model="res.partner",
                domain=[
                    [
                        "name",
                        "=",
                        company_name,
                    ],
                    [
                        "is_company",
                        "=",
                        True,
                    ],
                ],
                fields=[
                    "id",
                    "name",
                    "display_name",
                    "is_company",
                    "active",
                ],
                limit=1,
            )

            company_created = False

            if companies:
                company = companies[0]
                company_id = company["id"]
            else:
                company_id = await odoo.create(
                    model="res.partner",
                    values={
                        "name": company_name,
                        "is_company": True,
                    },
                )

                positive_id(
                    company_id,
                    "created_company_id",
                )

                company_created = True

                company_records = await odoo.read(
                    model="res.partner",
                    record_ids=[company_id],
                    fields=[
                        "id",
                        "name",
                        "display_name",
                            "is_company",
                        "active",
                    ],
                )

                if not company_records:
                    raise ValueError(
                        "Company was created but could not be read back."
                    )

                company = company_records[0]

            created_contacts = []
            existing_contacts = []

            for contact_name in cleaned_contact_names:
                existing = await odoo.search_read(
                    model="res.partner",
                    domain=[
                        [
                            "name",
                            "=",
                            contact_name,
                        ],
                        [
                            "parent_id",
                            "=",
                            company_id,
                        ],
                        [
                            "is_company",
                            "=",
                            False,
                        ],
                    ],
                    fields=[
                        "id",
                        "name",
                        "display_name",
                            "type",
                        "parent_id",
                        "active",
                    ],
                    limit=1,
                )

                if existing:
                    existing_contacts.append(
                        existing[0]
                    )
                    continue

                contact_id = await odoo.create(
                    model="res.partner",
                    values={
                        "name": contact_name,
                        "is_company": False,
                        "type": "contact",
                        "parent_id": company_id,
                    },
                )

                positive_id(
                    contact_id,
                    "created_contact_id",
                )

                contact_records = await odoo.read(
                    model="res.partner",
                    record_ids=[contact_id],
                    fields=[
                        "id",
                        "name",
                        "display_name",
                            "type",
                        "parent_id",
                        "active",
                    ],
                )

                if not contact_records:
                    raise ValueError(
                        f'Contact "{contact_name}" was created '
                        "but could not be read back."
                    )

                created_contacts.append(
                    contact_records[0]
                )

            log_tool(
                tool,
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "company_created": company_created,
                    "company": company,
                    "requested_contact_count": len(
                        cleaned_contact_names
                    ),
                    "created_contact_count": len(
                        created_contacts
                    ),
                    "existing_contact_count": len(
                        existing_contacts
                    ),
                    "created_contacts": created_contacts,
                    "existing_contacts": existing_contacts,
                    "message": (
                        "Company and person contacts processed successfully. "
                        "Existing matching records were not duplicated."
                    ),
                }
            )

        except Exception as exc:
            return failed(
                tool,
                exc,
                params,
            )

    # -----------------------------------------------------------------------
    # Business card import helpers
    # -----------------------------------------------------------------------

    def _card_text(value: Any) -> str:
        """Normalize text extracted by Claude from a business card."""
        if value is None:
            return ""
        return str(value).strip()

    def _email_domain(email: str) -> str:
        """Return the normalized domain from an email address."""
        email = _card_text(email).lower()
        if "@" not in email:
            return ""
        local_part, domain = email.rsplit("@", 1)
        if not local_part or not domain or "." not in domain:
            return ""
        return domain.strip().strip(".")

    def _company_name_from_email_domain(email: str) -> str:
        """Infer a conservative company name from a non-public email domain."""
        domain = _email_domain(email)
        if not domain:
            return ""

        public_domains = {
            "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk",
            "outlook.com", "hotmail.com", "live.com", "msn.com",
            "icloud.com", "me.com", "mac.com", "aol.com",
            "proton.me", "protonmail.com", "gmx.com", "mail.com",
            "zoho.com",
        }
        if domain in public_domains:
            return ""

        parts = [part for part in domain.split(".") if part]
        if len(parts) < 2:
            return ""

        common_second_level_suffixes = {
            "co", "com", "org", "net", "gov", "edu", "ac",
        }
        if (
            len(parts) >= 3
            and len(parts[-1]) == 2
            and parts[-2] in common_second_level_suffixes
        ):
            company_part = parts[-3]
        else:
            company_part = parts[-2]

        company_part = company_part.replace("-", " ").replace("_", " ").strip()
        if not company_part:
            return ""
        return " ".join(word.capitalize() for word in company_part.split())

    async def _find_company_by_name(name: str) -> list[dict[str, Any]]:
        """Find company partners using res.partner.name + is_company=True."""
        name = _card_text(name)
        if not name:
            return []
        return await odoo.search_read(
            model="res.partner",
            domain=[
                ["name", "=ilike", name],
                ["is_company", "=", True],
            ],
            fields=[
                "id", "name", "display_name", "is_company", "email",
                "phone", "mobile", "website", "street", "street2",
                "city", "state_id", "zip", "country_id", "active",
            ],
            limit=10,
            order="id asc",
        )

    async def _find_company_by_email_domain(email: str) -> list[dict[str, Any]]:
        """Find existing company partners by company email/website domain."""
        domain = _email_domain(email)
        if not domain:
            return []
        return await odoo.search_read(
            model="res.partner",
            domain=[
                ["is_company", "=", True],
                "|",
                ["email", "ilike", f"@{domain}"],
                ["website", "ilike", domain],
            ],
            fields=[
                "id", "name", "display_name", "is_company", "email",
                "phone", "mobile", "website", "street", "street2",
                "city", "state_id", "zip", "country_id", "active",
            ],
            limit=10,
            order="id asc",
        )

    async def _resolve_company_for_business_card(
        company: dict[str, Any] | None,
        person_email: str,
    ) -> dict[str, Any]:
        """
        Resolve the company for one business card.

        There is no company_name field.
        Company records use name + is_company=True.
        Person records use name + is_company=False.
        """
        company = company if isinstance(company, dict) else {}
        visible_company_name = _card_text(company.get("name"))
        email_domain = _email_domain(person_email)

        if visible_company_name:
            companies = await _find_company_by_name(visible_company_name)
            return {
                "status": "ambiguous" if len(companies) > 1 else "resolved",
                "name": visible_company_name,
                "name_source": "business_card",
                "companies": companies,
                "email_domain": email_domain or None,
            }

        if not email_domain:
            return {
                "status": "missing",
                "name": "",
                "name_source": None,
                "companies": [],
                "email_domain": None,
            }

        companies = await _find_company_by_email_domain(person_email)
        if len(companies) > 1:
            return {
                "status": "ambiguous",
                "name": "",
                "name_source": "email_domain_match",
                "companies": companies,
                "email_domain": email_domain,
            }
        if len(companies) == 1:
            return {
                "status": "resolved",
                "name": _card_text(companies[0].get("name")),
                "name_source": "email_domain_match",
                "companies": companies,
                "email_domain": email_domain,
            }

        inferred_name = _company_name_from_email_domain(person_email)
        if inferred_name:
            return {
                "status": "resolved",
                "name": inferred_name,
                "name_source": "email_domain_inferred",
                "companies": [],
                "email_domain": email_domain,
            }

        return {
            "status": "missing",
            "name": "",
            "name_source": None,
            "companies": [],
            "email_domain": email_domain,
        }

    async def _find_existing_person(
        name: str,
        company_id: int,
        email: str = "",
    ) -> dict[str, Any] | None:
        """Check person duplicates by email first, then name + parent company."""
        if email:
            records = await odoo.search_read(
                model="res.partner",
                domain=[
                    ["email", "=ilike", email],
                    ["is_company", "=", False],
                ],
                fields=[
                    "id", "name", "display_name", "email", "phone",
                    "mobile", "function", "parent_id", "is_company", "active",
                ],
                limit=1,
            )
            if records:
                return records[0]

        records = await odoo.search_read(
            model="res.partner",
            domain=[
                ["name", "=ilike", name],
                ["parent_id", "=", company_id],
                ["is_company", "=", False],
            ],
            fields=[
                "id", "name", "display_name", "email", "phone",
                "mobile", "function", "parent_id", "is_company", "active",
            ],
            limit=1,
        )
        return records[0] if records else None

    async def _get_or_create_record_source_tag(record_source: str) -> dict[str, Any]:
        tag_name = f"Source: {record_source}"
        existing = await odoo.search_read(
            model="res.partner.category",
            domain=[["name", "=ilike", tag_name]],
            fields=["id", "name"],
            limit=1,
        )
        if existing:
            return existing[0]

        tag_id = await odoo.create(
            model="res.partner.category",
            values={"name": tag_name},
        )
        positive_id(tag_id, "created_record_source_tag_id")
        tags = await odoo.read(
            model="res.partner.category",
            record_ids=[tag_id],
            fields=["id", "name"],
        )
        if not tags:
            raise ValueError("Record-source tag was created but could not be read back.")
        return tags[0]

    async def _resolve_country_id(country_name: str) -> int | None:
        if not country_name:
            return None
        countries = await odoo.search_read(
            model="res.country",
            domain=[["name", "=ilike", country_name]],
            fields=["id", "name", "code"],
            limit=1,
        )
        return countries[0]["id"] if countries else None

    async def _resolve_state_id(
        state_name: str,
        country_id: int | None,
    ) -> int | None:
        if not state_name:
            return None
        domain: list[Any] = [["name", "=ilike", state_name]]
        if country_id:
            domain.append(["country_id", "=", country_id])
        states = await odoo.search_read(
            model="res.country.state",
            domain=domain,
            fields=["id", "name", "code", "country_id"],
            limit=1,
        )
        return states[0]["id"] if states else None

    @mcp.tool()
    async def preview_business_card_contacts(
        record_source: str,
        cards: list[dict[str, Any]],
    ):
        """
        Preview business-card records extracted by Claude.

        Card structure:
        {
            "person": {
                "name": "Joe Nagy",
                "is_company": False,
                "job_title": "Sales",
                "email": "jnagy@peltierpro.com",
                "phone": "...",
                "mobile_no": "...",
                "website": "...",
                "street": "...",
                "street2": "...",
                "city": "...",
                "state": "...",
                "zip": "...",
                "country": "..."
            },
            "company": {
                "name": "Peltier",
                "is_company": True,
                "website": "peltierpro.com"
            }
        }

        The company object may be omitted when no company name is visible.
        In that case, the person's email domain is used to search/infer company.

        IMPORTANT:
        - There is no company_name field.
        - Company = name + is_company=True.
        - Person = name + is_company=False.
        - mobile_no is the Claude/MCP input key; it maps to Odoo mobile.
        - This tool never creates records.
        - Explicit confirmation is required before create_business_card_contacts.
        - No CRM lead/opportunity is created.
        """
        tool = "preview_business_card_contacts"
        params = {
            "record_source": record_source,
            "card_count": len(cards) if cards else 0,
        }

        try:
            record_source = _card_text(record_source)
            if not record_source:
                raise ValueError("record_source is required before processing business cards.")
            if not cards:
                raise ValueError("At least one business card is required.")
            if len(cards) > settings.max_results:
                raise ValueError(
                    f"Too many business cards. Maximum allowed is {settings.max_results}."
                )

            preview = []
            for index, raw_card in enumerate(cards, start=1):
                if not isinstance(raw_card, dict):
                    preview.append({
                        "index": index,
                        "status": "invalid",
                        "error": "Business card must be an object/dictionary.",
                    })
                    continue

                person = raw_card.get("person")
                company = raw_card.get("company")
                if not isinstance(person, dict):
                    preview.append({
                        "index": index,
                        "status": "invalid",
                        "error": "Business card must contain a person object.",
                    })
                    continue

                person_name = _card_text(person.get("name"))
                email = _card_text(person.get("email"))
                mobile_no = _card_text(person.get("mobile_no"))
                if not person_name:
                    preview.append({
                        "index": index,
                        "status": "invalid",
                        "error": "Business card has no readable person name.",
                    })
                    continue

                resolution = await _resolve_company_for_business_card(company, email)
                resolved_name = _card_text(resolution.get("name"))
                companies = resolution.get("companies") or []
                name_source = resolution.get("name_source")
                email_domain = resolution.get("email_domain")

                if resolution.get("status") == "missing":
                    preview.append({
                        "index": index,
                        "status": "needs_company",
                        "person": {
                            "name": person_name,
                            "is_company": False,
                            "email": email or None,
                            "mobile_no": mobile_no or None,
                        },
                        "company": None,
                        "email_domain": email_domain,
                        "error": (
                            "No company name is visible and the email could not safely "
                            "identify a company. Ask the user for the company before import."
                        ),
                    })
                    continue

                if resolution.get("status") == "ambiguous":
                    preview.append({
                        "index": index,
                        "status": "ambiguous_company",
                        "person": {
                            "name": person_name,
                            "is_company": False,
                            "email": email or None,
                            "mobile_no": mobile_no or None,
                        },
                        "company": {
                            "name": resolved_name or None,
                            "is_company": True,
                            "name_source": name_source,
                        },
                        "company_matches": companies,
                        "email_domain": email_domain,
                        "error": (
                            "Multiple Odoo companies matched. Ask the user to identify "
                            "the correct company; do not guess."
                        ),
                    })
                    continue

                if companies:
                    company_record = companies[0]
                    company_id = positive_id(company_record["id"], "company_id")
                    existing_person = await _find_existing_person(
                        name=person_name,
                        company_id=company_id,
                        email=email,
                    )
                    preview.append({
                        "index": index,
                        "status": (
                            "existing_person" if existing_person
                            else "ready_existing_company"
                        ),
                        "person": {
                            "name": person_name,
                            "is_company": False,
                            "email": email or None,
                            "mobile_no": mobile_no or None,
                        },
                        "company": {
                            "id": company_id,
                            "name": company_record.get("name"),
                            "is_company": True,
                            "name_source": name_source,
                        },
                        "email_domain": email_domain,
                        "company_exists": True,
                        "person_exists": bool(existing_person),
                        "existing_person": existing_person,
                    })
                else:
                    preview.append({
                        "index": index,
                        "status": "ready_new_company",
                        "person": {
                            "name": person_name,
                            "is_company": False,
                            "email": email or None,
                            "mobile_no": mobile_no or None,
                        },
                        "company": {
                            "name": resolved_name,
                            "is_company": True,
                            "name_source": name_source,
                        },
                        "email_domain": email_domain,
                        "company_exists": False,
                        "person_exists": False,
                    })

            log_tool(tool, params, success=True)
            return branded_response({
                "success": True,
                "record_source": record_source,
                "count": len(preview),
                "preview": preview,
                "write_performed": False,
                "requires_confirmation": True,
                "message": (
                    "Preview completed. No Odoo records were created. Obtain explicit "
                    "user confirmation before calling create_business_card_contacts "
                    "with user_confirmed=true."
                ),
            })
        except Exception as exc:
            return failed(tool, exc, params)

    @mcp.tool()
    async def create_business_card_contacts(
        record_source: str,
        cards: list[dict[str, Any]],
        user_confirmed: bool = False,
    ):
        """
        Create Odoo Contacts from business cards uploaded to Claude.

        HARD RULES:
        - user_confirmed must be True or nothing is created.
        - There is no company_name field.
        - Company uses name + is_company=True.
        - Person uses name + is_company=False.
        - Person is linked to company through parent_id.
        - mobile_no maps to Odoo's standard mobile field.
        - If company.name is missing, search/infer company using person email domain.
        - Existing companies/people are reused.
        - No crm.lead or opportunity is created.
        """
        tool = "create_business_card_contacts"
        params = {
            "record_source": record_source,
            "card_count": len(cards) if cards else 0,
            "user_confirmed": user_confirmed,
        }

        try:
            record_source = _card_text(record_source)
            if not record_source:
                raise ValueError("record_source is required before business-card import.")
            if user_confirmed is not True:
                return branded_response({
                    "success": False,
                    "created": False,
                    "requires_confirmation": True,
                    "message": (
                        "No records were created. Show the preview and obtain explicit "
                        "user confirmation, then call again with user_confirmed=true."
                    ),
                })
            if not cards:
                raise ValueError("At least one business card is required.")
            if len(cards) > settings.max_results:
                raise ValueError(
                    f"Too many business cards. Maximum allowed is {settings.max_results}."
                )

            source_tag = await _get_or_create_record_source_tag(record_source)
            source_tag_id = positive_id(source_tag["id"], "record_source_tag_id")

            created_companies = []
            reused_companies = []
            created_contacts = []
            existing_contacts = []
            skipped_contacts = []
            company_cache: dict[str, dict[str, Any]] = {}

            for index, raw_card in enumerate(cards, start=1):
                if not isinstance(raw_card, dict):
                    skipped_contacts.append({
                        "index": index,
                        "reason": "Business card must be an object/dictionary.",
                    })
                    continue

                person = raw_card.get("person")
                company = raw_card.get("company")
                if not isinstance(person, dict):
                    skipped_contacts.append({
                        "index": index,
                        "reason": "Business card must contain a person object.",
                    })
                    continue

                person_name = _card_text(person.get("name"))
                job_title = _card_text(person.get("job_title"))
                email = _card_text(person.get("email"))
                phone = _card_text(person.get("phone"))
                mobile_no = _card_text(person.get("mobile_no"))
                website = _card_text(person.get("website"))
                street = _card_text(person.get("street"))
                street2 = _card_text(person.get("street2"))
                city = _card_text(person.get("city"))
                state = _card_text(person.get("state"))
                zip_code = _card_text(person.get("zip"))
                country = _card_text(person.get("country"))

                if not person_name:
                    skipped_contacts.append({
                        "index": index,
                        "reason": "Business card has no readable person name.",
                    })
                    continue

                resolution = await _resolve_company_for_business_card(company, email)
                resolved_name = _card_text(resolution.get("name"))
                companies = resolution.get("companies") or []
                name_source = resolution.get("name_source")
                email_domain = resolution.get("email_domain")

                if resolution.get("status") == "missing":
                    skipped_contacts.append({
                        "index": index,
                        "person": {"name": person_name, "is_company": False},
                        "email": email or None,
                        "email_domain": email_domain,
                        "reason": (
                            "No company name is visible and the email could not safely "
                            "identify a company. Contact was not created."
                        ),
                    })
                    continue

                if resolution.get("status") == "ambiguous":
                    skipped_contacts.append({
                        "index": index,
                        "person": {"name": person_name, "is_company": False},
                        "company_matches": companies,
                        "reason": (
                            "Multiple matching Odoo companies were found. Card was "
                            "skipped to avoid linking to the wrong company."
                        ),
                    })
                    continue

                cache_key = resolved_name.casefold()
                company_record = company_cache.get(cache_key)
                company_was_created = False

                if company_record is None:
                    if companies:
                        company_record = companies[0]
                        reused_companies.append({
                            "card_index": index,
                            "name_source": name_source,
                            "email_domain": email_domain,
                            "company": company_record,
                        })
                    else:
                        company_input = company if isinstance(company, dict) else {}
                        company_website = _card_text(company_input.get("website")) or website
                        company_phone = _card_text(company_input.get("phone"))
                        company_mobile_no = _card_text(company_input.get("mobile_no"))
                        company_street = _card_text(company_input.get("street")) or street
                        company_street2 = _card_text(company_input.get("street2")) or street2
                        company_city = _card_text(company_input.get("city")) or city
                        company_state = _card_text(company_input.get("state")) or state
                        company_zip = _card_text(company_input.get("zip")) or zip_code
                        company_country = _card_text(company_input.get("country")) or country

                        country_id = await _resolve_country_id(company_country)
                        state_id = await _resolve_state_id(company_state, country_id)

                        company_values: dict[str, Any] = {
                            "name": resolved_name,
                            "is_company": True,
                            "type": "contact",
                            "category_id": [[6, 0, [source_tag_id]]],
                            "comment": (
                                "<p><strong>Record Source:</strong> "
                                f"{escape(record_source)}</p>"
                                "<p>Company created during Claude business-card import.</p>"
                            ),
                        }
                        if company_website:
                            company_values["website"] = company_website
                        if company_phone:
                            company_values["phone"] = company_phone
                        if company_mobile_no:
                            company_values["mobile"] = company_mobile_no
                        if company_street:
                            company_values["street"] = company_street
                        if company_street2:
                            company_values["street2"] = company_street2
                        if company_city:
                            company_values["city"] = company_city
                        if company_zip:
                            company_values["zip"] = company_zip
                        if country_id:
                            company_values["country_id"] = country_id
                        if state_id:
                            company_values["state_id"] = state_id

                        company_id = await odoo.create(
                            model="res.partner",
                            values=company_values,
                        )
                        positive_id(company_id, "created_company_id")
                        company_records = await odoo.read(
                            model="res.partner",
                            record_ids=[company_id],
                            fields=[
                                "id", "name", "display_name", "is_company", "website",
                                "phone", "mobile", "street", "street2", "city",
                                "state_id", "zip", "country_id", "category_id", "active",
                            ],
                        )
                        if not company_records:
                            raise ValueError(
                                f'Company "{resolved_name}" was created but could not be read back.'
                            )
                        company_record = company_records[0]
                        company_was_created = True
                        created_companies.append({
                            "card_index": index,
                            "name_source": name_source,
                            "email_domain": email_domain,
                            "company": company_record,
                        })

                    company_cache[cache_key] = company_record

                company_id = positive_id(company_record["id"], "company_id")
                existing_person = await _find_existing_person(
                    name=person_name,
                    company_id=company_id,
                    email=email,
                )
                if existing_person:
                    existing_contacts.append({
                        "card_index": index,
                        "record_source": record_source,
                        "company": {
                            "id": company_id,
                            "name": company_record.get("name"),
                            "is_company": True,
                        },
                        "contact": existing_person,
                        "reason": "Matching person contact already exists.",
                    })
                    continue

                country_id = await _resolve_country_id(country)
                state_id = await _resolve_state_id(state, country_id)

                person_values: dict[str, Any] = {
                    "name": person_name,
                    "is_company": False,
                    "type": "contact",
                    "parent_id": company_id,
                    "category_id": [[6, 0, [source_tag_id]]],
                    "comment": (
                        "<p><strong>Record Source:</strong> "
                        f"{escape(record_source)}</p>"
                        "<p>Created from a business card uploaded to Claude.</p>"
                    ),
                }
                if job_title:
                    person_values["function"] = job_title
                if email:
                    person_values["email"] = email
                if phone:
                    person_values["phone"] = phone
                if mobile_no:
                    person_values["mobile"] = mobile_no
                if website:
                    person_values["website"] = website
                if street:
                    person_values["street"] = street
                if street2:
                    person_values["street2"] = street2
                if city:
                    person_values["city"] = city
                if zip_code:
                    person_values["zip"] = zip_code
                if country_id:
                    person_values["country_id"] = country_id
                if state_id:
                    person_values["state_id"] = state_id

                contact_id = await odoo.create(
                    model="res.partner",
                    values=person_values,
                )
                positive_id(contact_id, "created_contact_id")
                contact_records = await odoo.read(
                    model="res.partner",
                    record_ids=[contact_id],
                    fields=[
                        "id", "name", "display_name", "is_company", "type",
                        "parent_id", "email", "phone", "mobile", "website",
                        "street", "street2", "city", "state_id", "zip",
                        "country_id", "function", "category_id", "active",
                    ],
                )
                if not contact_records:
                    raise ValueError(
                        f'Contact "{person_name}" was created but could not be read back.'
                    )

                created_contacts.append({
                    "card_index": index,
                    "record_source": record_source,
                    "company_created": company_was_created,
                    "company": {
                        "id": company_id,
                        "name": company_record.get("name"),
                        "is_company": True,
                        "name_source": name_source,
                    },
                    "contact": contact_records[0],
                })

            log_tool(tool, params, success=True)
            return branded_response({
                "success": True,
                "record_source": record_source,
                "source_tag": source_tag,
                "requested_card_count": len(cards),
                "created_company_count": len(created_companies),
                "reused_company_count": len(reused_companies),
                "created_contact_count": len(created_contacts),
                "existing_contact_count": len(existing_contacts),
                "skipped_contact_count": len(skipped_contacts),
                "created_companies": created_companies,
                "reused_companies": reused_companies,
                "created_contacts": created_contacts,
                "existing_contacts": existing_contacts,
                "skipped_contacts": skipped_contacts,
                "message": (
                    "Business-card import completed as Odoo Contacts. Companies use "
                    "name + is_company=True; people use name + is_company=False and "
                    "are linked through parent_id. No CRM opportunity was created."
                ),
            })
        except Exception as exc:
            return failed(tool, exc, params)
