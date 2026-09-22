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

    async def _find_company_by_name(
        company_name: str,
    ) -> list[dict[str, Any]]:
        """
        Find company contacts using an exact, case-insensitive company name.

        More than one match is returned so the caller can avoid silently
        linking a person to the wrong company when Odoo contains duplicates.
        """
        return await odoo.search_read(
            model="res.partner",
            domain=[
                [
                    "name",
                    "=ilike",
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
                "email",
                "phone",
                "website",
                "street",
                "street2",
                "city",
                "state_id",
                "zip",
                "country_id",
                "active",
            ],
            limit=10,
            order="id asc",
        )

    async def _find_existing_person(
        name: str,
        company_id: int,
        email: str = "",
    ) -> dict[str, Any] | None:
        """
        Find an existing person contact.

        Matching order:
        1. Exact email address when available.
        2. Exact person name under the identified company.
        """
        if email:
            records = await odoo.search_read(
                model="res.partner",
                domain=[
                    [
                        "email",
                        "=ilike",
                        email,
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
                    "email",
                    "phone",
                    "mobile",
                    "function",
                    "parent_id",
                    "active",
                ],
                limit=1,
            )

            if records:
                return records[0]

        records = await odoo.search_read(
            model="res.partner",
            domain=[
                [
                    "name",
                    "=ilike",
                    name,
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
                "email",
                "phone",
                "mobile",
                "function",
                "parent_id",
                "active",
            ],
            limit=1,
        )

        if records:
            return records[0]

        return None

    async def _get_or_create_record_source_tag(
        record_source: str,
    ) -> dict[str, Any]:
        """
        Store the business-card record source as a standard Odoo contact tag.

        This avoids requiring a custom field on res.partner while still making
        the import source visible and searchable in Odoo Contacts.
        """
        tag_name = f"Source: {record_source}"

        existing = await odoo.search_read(
            model="res.partner.category",
            domain=[
                [
                    "name",
                    "=ilike",
                    tag_name,
                ]
            ],
            fields=[
                "id",
                "name",
            ],
            limit=1,
        )

        if existing:
            return existing[0]

        tag_id = await odoo.create(
            model="res.partner.category",
            values={
                "name": tag_name,
            },
        )

        positive_id(
            tag_id,
            "created_record_source_tag_id",
        )

        tags = await odoo.read(
            model="res.partner.category",
            record_ids=[tag_id],
            fields=[
                "id",
                "name",
            ],
        )

        if not tags:
            raise ValueError(
                "Record-source tag was created but could not be read back."
            )

        return tags[0]

    async def _resolve_country_id(
        country_name: str,
    ) -> int | None:
        if not country_name:
            return None

        countries = await odoo.search_read(
            model="res.country",
            domain=[
                [
                    "name",
                    "=ilike",
                    country_name,
                ]
            ],
            fields=[
                "id",
                "name",
                "code",
            ],
            limit=1,
        )

        if not countries:
            return None

        return countries[0]["id"]

    async def _resolve_state_id(
        state_name: str,
        country_id: int | None,
    ) -> int | None:
        if not state_name:
            return None

        domain: list[Any] = [
            [
                "name",
                "=ilike",
                state_name,
            ]
        ]

        if country_id:
            domain.append(
                [
                    "country_id",
                    "=",
                    country_id,
                ]
            )

        states = await odoo.search_read(
            model="res.country.state",
            domain=domain,
            fields=[
                "id",
                "name",
                "code",
                "country_id",
            ],
            limit=1,
        )

        if not states:
            return None

        return states[0]["id"]

    # -----------------------------------------------------------------------
    # Preview business cards extracted by Claude
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def preview_business_card_contacts(
        record_source: str,
        contacts: list[dict[str, Any]],
    ):
        """
        Preview business-card contacts extracted from PDF/image uploads in Claude.

        IMPORTANT CLAUDE WORKFLOW:
        1. Ask the user for a record source FIRST, for example "GroceryShop 2026".
        2. The user may then upload one or more business-card images/PDFs to Claude.
        3. Claude reads the cards and extracts structured contact information.
        4. Call this preview tool BEFORE creating anything in Odoo.
        5. Show the preview to the user and obtain approval.
        6. Only after approval call create_business_card_contacts.

        This tool DOES NOT create CRM opportunities and DOES NOT create contacts.
        It only checks Odoo Contacts (res.partner) and reports whether each card's
        company already exists, including its Odoo company/contact ID.

        Required contact keys:
        - name
        - company_name

        Optional contact keys:
        - job_title
        - email
        - phone
        - mobile
        - website
        - street
        - street2
        - city
        - state
        - zip
        - country

        Never guess unreadable values from a business card. Claude should send an
        empty string or null for fields it cannot confidently extract.
        """

        tool = "preview_business_card_contacts"

        params = {
            "record_source": record_source,
            "contact_count": len(contacts) if contacts else 0,
        }

        try:
            record_source = _card_text(record_source)

            if not record_source:
                raise ValueError(
                    "record_source is required before processing business cards. "
                    "Ask the user for a source such as 'GroceryShop 2026'."
                )

            if not contacts:
                raise ValueError(
                    "At least one business-card contact is required."
                )

            if len(contacts) > settings.max_results:
                raise ValueError(
                    f"Too many business cards. Maximum allowed is {settings.max_results}."
                )

            preview = []

            for index, raw_contact in enumerate(
                contacts,
                start=1,
            ):
                if not isinstance(raw_contact, dict):
                    preview.append(
                        {
                            "index": index,
                            "status": "invalid",
                            "error": "Contact must be an object/dictionary.",
                        }
                    )
                    continue

                name = _card_text(
                    raw_contact.get("name")
                )
                company_name = _card_text(
                    raw_contact.get("company_name")
                )
                email = _card_text(
                    raw_contact.get("email")
                )

                if not name:
                    preview.append(
                        {
                            "index": index,
                            "status": "invalid",
                            "company_name": company_name or None,
                            "error": "Business card has no readable person name.",
                        }
                    )
                    continue

                if not company_name:
                    preview.append(
                        {
                            "index": index,
                            "status": "invalid",
                            "name": name,
                            "error": (
                                "Business card has no readable company name. "
                                "Company is required so the person can be linked "
                                "to an Odoo company contact."
                            ),
                        }
                    )
                    continue

                companies = await _find_company_by_name(
                    company_name
                )

                if len(companies) > 1:
                    preview.append(
                        {
                            "index": index,
                            "status": "ambiguous_company",
                            "name": name,
                            "email": email or None,
                            "company_name": company_name,
                            "company_exists": True,
                            "company_matches": companies,
                            "error": (
                                "Multiple Odoo company contacts have this name. "
                                "Do not create/link automatically until the correct "
                                "company ID is identified."
                            ),
                        }
                    )
                    continue

                if companies:
                    company = companies[0]
                    company_id = positive_id(
                        company["id"],
                        "company_id",
                    )

                    existing_person = await _find_existing_person(
                        name=name,
                        company_id=company_id,
                        email=email,
                    )

                    preview.append(
                        {
                            "index": index,
                            "status": (
                                "existing_person"
                                if existing_person
                                else "ready_existing_company"
                            ),
                            "name": name,
                            "email": email or None,
                            "company_name": company_name,
                            "company_exists": True,
                            "company_id": company_id,
                            "company": company,
                            "person_exists": bool(existing_person),
                            "existing_person": existing_person,
                        }
                    )
                    continue

                preview.append(
                    {
                        "index": index,
                        "status": "ready_new_company",
                        "name": name,
                        "email": email or None,
                        "company_name": company_name,
                        "company_exists": False,
                        "company_id": None,
                        "person_exists": False,
                        "message": (
                            "Company was not found in Odoo. On approved import, "
                            "a company contact will be created first and then used "
                            "as the Company/parent_id of the person contact."
                        ),
                    }
                )

            log_tool(
                tool,
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "record_source": record_source,
                    "count": len(preview),
                    "preview": preview,
                    "write_performed": False,
                    "message": (
                        "Preview completed. No Odoo records were created. "
                        "After user approval, call create_business_card_contacts."
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
    # Create person contacts from Claude business-card extraction
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def create_business_card_contacts(
        record_source: str,
        contacts: list[dict[str, Any]],
        user_confirmed: bool = False,
    ):
        """
        Create Odoo person contacts from business cards uploaded to Claude.

        CONDITIONS / SAFETY RULES:
        - record_source is mandatory and must be identified by the user first.
        - Claude should call preview_business_card_contacts first.
        - user_confirmed must be True. If False, nothing is created.
        - This tool creates res.partner contacts ONLY. It never creates crm.lead,
          crm.opportunity, or a new opportunity from a business card.
        - Each person must have a readable company_name.
        - If the company already exists as an Odoo company contact, its existing
          res.partner ID is used as the person's parent_id / Company.
        - If the company does not exist, a new company res.partner is created first,
          then that new company ID is used as the person's parent_id / Company.
        - If multiple Odoo companies have the same exact name, the card is skipped
          as ambiguous rather than linking it to the wrong company.
        - Existing person contacts are reused instead of duplicated. Email is the
          first duplicate check, then person name + company.
        - The source is stored as an Odoo Contact tag named "Source: <record_source>"
          and is also written into the person's Notes field.
        - Claude must not invent unreadable business-card fields. Unknown values
          should be omitted, null, or empty.

        Required contact keys:
        - name
        - company_name

        Optional contact keys:
        - job_title
        - email
        - phone
        - mobile
        - website
        - street
        - street2
        - city
        - state
        - zip
        - country
        """

        tool = "create_business_card_contacts"

        params = {
            "record_source": record_source,
            "contact_count": len(contacts) if contacts else 0,
            "user_confirmed": user_confirmed,
        }

        try:
            record_source = _card_text(record_source)

            if not record_source:
                raise ValueError(
                    "record_source is required before business-card import."
                )

            if user_confirmed is not True:
                return branded_response(
                    {
                        "success": False,
                        "created": False,
                        "requires_confirmation": True,
                        "message": (
                            "No records were created. Preview the extracted cards "
                            "and obtain explicit user approval, then call this tool "
                            "again with user_confirmed=true."
                        ),
                    }
                )

            if not contacts:
                raise ValueError(
                    "At least one business-card contact is required."
                )

            if len(contacts) > settings.max_results:
                raise ValueError(
                    f"Too many business cards. Maximum allowed is {settings.max_results}."
                )

            source_tag = await _get_or_create_record_source_tag(
                record_source
            )
            source_tag_id = positive_id(
                source_tag["id"],
                "record_source_tag_id",
            )

            created_companies = []
            reused_companies = []
            created_contacts = []
            existing_contacts = []
            skipped_contacts = []

            # Cache company matches within this import so multiple cards from the
            # same organization do not repeatedly search/create the same company.
            company_cache: dict[str, dict[str, Any]] = {}

            for index, raw_contact in enumerate(
                contacts,
                start=1,
            ):
                if not isinstance(raw_contact, dict):
                    skipped_contacts.append(
                        {
                            "index": index,
                            "reason": "Contact must be an object/dictionary.",
                        }
                    )
                    continue

                name = _card_text(
                    raw_contact.get("name")
                )
                company_name = _card_text(
                    raw_contact.get("company_name")
                )
                job_title = _card_text(
                    raw_contact.get("job_title")
                )
                email = _card_text(
                    raw_contact.get("email")
                )
                phone = _card_text(
                    raw_contact.get("phone")
                )
                mobile = _card_text(
                    raw_contact.get("mobile")
                )
                website = _card_text(
                    raw_contact.get("website")
                )
                street = _card_text(
                    raw_contact.get("street")
                )
                street2 = _card_text(
                    raw_contact.get("street2")
                )
                city = _card_text(
                    raw_contact.get("city")
                )
                state = _card_text(
                    raw_contact.get("state")
                )
                zip_code = _card_text(
                    raw_contact.get("zip")
                )
                country = _card_text(
                    raw_contact.get("country")
                )

                if not name:
                    skipped_contacts.append(
                        {
                            "index": index,
                            "company_name": company_name or None,
                            "reason": "Business card has no readable person name.",
                        }
                    )
                    continue

                if not company_name:
                    skipped_contacts.append(
                        {
                            "index": index,
                            "name": name,
                            "reason": (
                                "Business card has no readable company name. "
                                "Person was not created because Company is required."
                            ),
                        }
                    )
                    continue

                cache_key = company_name.casefold()
                company = company_cache.get(
                    cache_key
                )
                company_was_created = False

                if company is None:
                    companies = await _find_company_by_name(
                        company_name
                    )

                    if len(companies) > 1:
                        skipped_contacts.append(
                            {
                                "index": index,
                                "name": name,
                                "company_name": company_name,
                                "reason": (
                                    "Multiple matching Odoo company contacts were found. "
                                    "Card was skipped to avoid linking to the wrong company."
                                ),
                                "company_matches": companies,
                            }
                        )
                        continue

                    if companies:
                        company = companies[0]
                        reused_companies.append(
                            {
                                "card_index": index,
                                "company": company,
                            }
                        )
                    else:
                        country_id = await _resolve_country_id(
                            country
                        )
                        state_id = await _resolve_state_id(
                            state,
                            country_id,
                        )

                        company_values: dict[str, Any] = {
                            "name": company_name,
                            "is_company": True,
                            "type": "contact",
                            "category_id": [
                                [
                                    6,
                                    0,
                                    [source_tag_id],
                                ]
                            ],
                            "comment": (
                                "<p><strong>Record Source:</strong> "
                                f"{escape(record_source)}</p>"
                                "<p>Company created during Claude business-card import.</p>"
                            ),
                        }

                        if website:
                            company_values["website"] = website
                        if street:
                            company_values["street"] = street
                        if street2:
                            company_values["street2"] = street2
                        if city:
                            company_values["city"] = city
                        if zip_code:
                            company_values["zip"] = zip_code
                        if country_id:
                            company_values["country_id"] = country_id
                        if state_id:
                            company_values["state_id"] = state_id

                        company_id = await odoo.create(
                            model="res.partner",
                            values=company_values,
                        )

                        positive_id(
                            company_id,
                            "created_company_id",
                        )

                        company_records = await odoo.read(
                            model="res.partner",
                            record_ids=[company_id],
                            fields=[
                                "id",
                                "name",
                                "display_name",
                                "is_company",
                                "website",
                                "street",
                                "street2",
                                "city",
                                "state_id",
                                "zip",
                                "country_id",
                                "category_id",
                                "active",
                            ],
                        )

                        if not company_records:
                            raise ValueError(
                                f'Company "{company_name}" was created but could not be read back.'
                            )

                        company = company_records[0]
                        company_was_created = True
                        created_companies.append(
                            {
                                "card_index": index,
                                "company": company,
                            }
                        )

                    company_cache[cache_key] = company

                company_id = positive_id(
                    company["id"],
                    "company_id",
                )

                existing_person = await _find_existing_person(
                    name=name,
                    company_id=company_id,
                    email=email,
                )

                if existing_person:
                    existing_contacts.append(
                        {
                            "card_index": index,
                            "record_source": record_source,
                            "company_id": company_id,
                            "company_name": company.get("name"),
                            "contact": existing_person,
                            "reason": "Matching person contact already exists.",
                        }
                    )
                    continue

                country_id = await _resolve_country_id(
                    country
                )
                state_id = await _resolve_state_id(
                    state,
                    country_id,
                )

                person_values: dict[str, Any] = {
                    "name": name,
                    "is_company": False,
                    "type": "contact",
                    "parent_id": company_id,
                    "category_id": [
                        [
                            6,
                            0,
                            [source_tag_id],
                        ]
                    ],
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
                if mobile:
                    person_values["mobile"] = mobile
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
                        "function",
                        "category_id",
                        "active",
                    ],
                )

                if not contact_records:
                    raise ValueError(
                        f'Contact "{name}" was created but could not be read back.'
                    )

                created_contacts.append(
                    {
                        "card_index": index,
                        "record_source": record_source,
                        "company_created": company_was_created,
                        "company_id": company_id,
                        "company_name": company.get("name"),
                        "contact": contact_records[0],
                    }
                )

            log_tool(
                tool,
                params,
                success=True,
            )

            return branded_response(
                {
                    "success": True,
                    "record_source": record_source,
                    "source_tag": source_tag,
                    "requested_card_count": len(contacts),
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
                        "Business-card import completed as Odoo Contacts. "
                        "No CRM opportunity was created. Existing Odoo company "
                        "contacts were reused by ID; missing companies were created "
                        "and linked as the Company of each person contact."
                    ),
                }
            )

        except Exception as exc:
            return failed(
                tool,
                exc,
                params,
            )

