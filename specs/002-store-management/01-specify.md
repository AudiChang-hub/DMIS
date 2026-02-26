# Store Management Specification (Master Context)

This specification defines the Store/Dealer master-data schema, UI and governance required for long-lived operation of the Store (Dealer) master record in DMIS. It belongs to the Master Context and intentionally excludes import pipelines, incentive calculations, and analytic materializations (those belong to specs/003, specs/004, specs/005 respectively).

Scope
- Owner: Master Context
- In-scope: authoritative `dms.dealer` master record (fields, validations, UI behaviour, access control), `dms.dealer.tag` taxonomy, and seed/demo data for onboarding.
- Out-of-scope: import pipelines, outbox/worker, calculation engines, and analytic materialized views.

Required Field Model (suggested Odoo field names)

Basic Information
- store name (required): `name` (fields.Char, required=True)
- owner (required): `owner_name` (fields.Char, required=True)
- manager (required): `store_manager` (fields.Char, required=True)
- address (optional): `address` (fields.Text)
- note (optional): `note` (fields.Html)

Contact Information
- phone 1 (optional): `phone_1` (fields.Char)
- phone 2 (optional): `phone_2` (fields.Char)
- mobile (optional): `mobile` (fields.Char)
- fax_or_mobile (optional): `mobile_fax` (fields.Char)

Price-Table Permissions (checkboxes)
- sanyang_fuel_price (boolean): 三陽油車價格表
- sanyang_electric_price (boolean): 三陽電車價格表
- tailin_fuel_price (boolean): 台鈴油車價格表
- tailin_electric_price (boolean): 台鈴電車價格表

CapaCities
- `sym_dispatch_capacity` (integer, optional): 三陽排車容量 (non-negative integer)
- `suzuki_dispatch_capacity` (integer, optional): 台鈴排車容量 (non-negative integer)

Groups / Activities (checkboxes)
- sanyang_line_group (boolean)
- tailin_line_group (boolean)
- common_line_group (boolean)
- special_line_group (boolean)
- holiday_gift (boolean)

Other master-data fields (recommended)
- code (unique identifier): `code` (fields.Char, required=True, unique)
- short_name: `short_name` (fields.Char)
- store_type: `store_type` (fields.Selection)
- parent/child hierarchy: `parent_id` / `child_ids` (Many2one / One2many)
- tags: `tags` (Many2many to `dms.dealer.tag`)

Validation & Governance Rules
- `code` and `name` MUST be present and `code` MUST be unique (SQL constraint).
- `owner_name` and `store_manager` MUST be present.
- Capacities (`sym_dispatch_capacity`, `suzuki_dispatch_capacity`) MUST be non-negative integers if provided (validation in Python).
- `parent_id` MUST NOT point to self and MUST NOT create cycles (python constraint to detect loops).
- No import wizards or direct file ingestion logic are allowed in this spec (imports must be handled by `specs/003-import-pipeline`).

UI Behaviour
- `name_get` should present as "[code] name" when referenced in Many2one widgets.
- `name_search` should search by `code`, `name`, `phone_1`, `phone_2`, `mobile`, and `short_name`.
- Tree view suggested columns: `code`, `name`, `short_name`, `store_type`, `phone_1`, `city`, `active`.
- Form view should use a `notebook` with pages: Basic Information / Contact Information / Price Permissions & Capacities / Groups & Tags / Notes.
- Search view should include filters for `active`, `store_type`, and group-by options for `store_type`, `city`.

DoD / Acceptance Criteria
- Create: user can create a dealer record with required fields (`code`, `name`, `owner_name`, `manager_name`).
- Edit: user can update optional fields without data loss; existing records remain readable.
- Search: search and name_get/name_search behave as specified (including `short_name`).
- Validation: `code` uniqueness, non-negative capacities, and parent-cycle prevention enforced.
- Permissions: groups for read-only and manager roles control create/edit/delete as specified in `specs/002-store-management/04-tasks.md`.
- Smoke: after module install/upgrade, smoke script must still return healthy HTTP response and basic create/read operations pass.

Field Mapping Note
- The suggested Odoo field names above are recommendations; implementation must keep `code` and `name` compatible with existing data and provide migration steps if renaming is required.
