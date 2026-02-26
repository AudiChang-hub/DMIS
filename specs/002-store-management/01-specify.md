# Store Management Specification (Master Context)

This specification defines the Store/Dealer Master Data responsibilities for DMIS. It belongs to the Master Context and focuses exclusively on authoritative store records, their governance, and extension points. Implementation details for import pipelines, incentive calculations, and analytics are out of scope and belong to specs 003/004/005 respectively.

Scope
- Owner: Master Context
- In-scope: CRUD and governance for `dms.dealer` master records, tagging, hierarchical organization, contact points, basic organizational attributes.
- Out-of-scope: import pipelines (specs/003), incentive calculations (specs/004), analytics/materialized views (specs/005).

Key Principles
- Authoritative Source: `dms.dealer` in Core Transaction is the single source of truth for store master data.
- Auditability: changes to master data must be traceable; seed/demo data is not considered authoritative.
- Extensibility: model must provide explicit extension points (tags, partner links, parent/child relations) without embedding domain-specific calculations.

Core Entities
- `dms.dealer`: primary store/dealer master record. Fields include unique `code`, `name`, `short_name`, `store_type`, hierarchical `parent_id/child_ids`, contact fields, `city`, `district`, `tags` (Many2many), `note`.
- `dms.dealer.tag`: lightweight taxonomy for store tags used by other contexts.

Governance Requirements (must)
- All external/imported data MUST go through `specs/003-import-pipeline` and land in Staging before being applied to Core.
- Master edits through UI/API are allowed but must respect validation rules and not perform domain calculations.
- Changes to master schema must be proposed via spec updates and PRs referencing this charter (specs/001).
