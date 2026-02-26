
# DMS Architecture Charter

This document is the Architecture Charter for the Dealer Management Intelligence System (DMIS). It sets the authoritative architectural principles and governance rules that all feature specifications (002+) and implementation efforts must follow.

## 1. Bounded Contexts

The system is organized into the following bounded contexts. Each context owns specific responsibilities and data, and communicates via well-defined interfaces (events, APIs, or read-models).

| Context | Responsibilities | Owned Data / Entities | Out of Scope | Dependencies | Inputs / Outputs |
|---|---|---|---|---|---|
| Master Context | Manage core master data (customers, stores, products, users). Serve as the canonical registry for identity and reference data. | Master entities: Customer, Store, Product, User | Business transactions (sales, incentives computation) | Read-only to Core Transaction for reference; consumed by Sales/Import | Inputs: admin UI/API; Outputs: master read-models, events (master.updated) |
| Sales Context | Handle sales transactions lifecycle (orders, invoices), enforce business rules for sales processing. | Transactional entities: Order, Invoice, Payment | Incentive calculation engine internals | Depends on Master for reference data; publishes events to Incentive/Analytics | Inputs: order APIs, POS; Outputs: sales events, transactional table rows |
| Incentive Context | Define, version, and execute incentive/commission/subsidy rules; provide calculation results and histories. | Rule definitions, Rule versions, Calculation results | Raw sales ingestion (handled by Sales/Import) | Consumes Sales events; provides computed results to Reporting | Inputs: sales events, rule versions; Outputs: calculation records, audit logs, events (incentive.calculated) |
| Import Context | Ingest external data sources (CSV/Excel/API), validate and land raw data into Staging. Provide replayable import pipelines. | Staging tables, import job metadata, import audit | Core transaction responsibilities (no write to core except via controlled transforms) | Produces cleaned data for Core Transaction and outbox events | Inputs: files/APIs; Outputs: staging records, import events, validation reports |
| Analytics Context | Provide read-only analytical models, materialized views, and BI interfaces for reporting and dashboards. | Materialized views, aggregated facts, BI schemas | Serving transactional writes | Depends on Core Transaction and Incentive for source data; consumes events or ETL outputs | Inputs: DB views, event streams; Outputs: BI datasets, dashboards |

## 2. Data Layering and Governance

DMIS uses a three-layer data architecture. These layers are governance boundaries and have strict rules.

- Staging Layer
	- Purpose: land raw external data (file uploads, external APIs) unchanged; preserve original fields and file provenance.
	- Hard Rules:
		- External/Excel data MUST land in Staging first.
		- Staging data must include import metadata (source, timestamp, filename, row id) for traceability.
		- Staging must be idempotent and replayable: re-running the same import must not corrupt or duplicate canonical data.

- Core Transaction Layer (Single Source of Truth)
	- Purpose: the authoritative transactional model used by the application (Odoo-based core). This is the source of truth for live business operations.
	- Hard Rules:
		- Core is the single source of truth for transactions and authoritative state.
		- Raw data MUST NOT be overwritten by computed results; separate fields/tables must hold computed outputs.
		- Writes to Core from imports must follow controlled transforms and validation; direct writes from spreadsheets or ad-hoc scripts are forbidden.

- Reporting Layer
	- Purpose: provide read-only views, materialized views, and denormalized aggregates for BI and analytics.
	- Hard Rules:
		- Reporting layer MUST be read-only relative to application code; all changes flow from Core or from controlled ETL processes.
		- Reporting views should be refreshable and include provenance links back to Core/Import records.

## 3. Rule & Calculation Versioning

Calculation rule governance is critical for auditability and repeatable back-calculation.

- Rules MUST be versioned and carry effective_start and effective_end timestamps (or explicit version identifiers).
- Historical recalculation MUST be supported: given a past transaction and a rule version, the system must be able to re-run the calculation and reproduce historical results.
- Raw inputs and computed outputs MUST be stored separately (raw_inputs table vs computed_results table); computed results should reference the rule version used.
- Multiple program results per transaction are allowed (e.g., same transaction evaluated under multiple campaigns/versions); all results must be traceable.

## 4. Container Responsibilities (Docker)

Minimum service topology and responsibilities:

- odoo
	- Responsibilities: run the Core Transaction application (Odoo); host transactional models and UI.
	- Must Not Do: heavy batch computation, long-running ETL tasks.
	- Key Interfaces: Postgres DB, outbox table (DB), optional Redis for cache/session.

- db (Postgres)
	- Responsibilities: durable storage for Core, Staging, outbox, and audit logs.
	- Must Not Do: perform application-level computations.
	- Key Interfaces: SQL, logical replication for BI, maintenance roles.

- redis
	- Responsibilities: caching, task queue broker (if used), session store (optional).
	- Must Not Do: act as persistent data store; do not store single source of truth here.

- worker-import
	- Responsibilities: run import pipelines, validate staging data, transform and write to Core or enqueue outbox events.
	- Must Not Do: write ad-hoc changes to Core outside controlled transforms.
	- Key Interfaces: reads from staging tables/files, writes to Postgres and outbox.

- worker-compute
	- Responsibilities: execute heavy computations (incentive calculations), write computed_results, and publish events.
	- Must Not Do: serve UI requests or host the Core application.
	- Key Interfaces: reads Core and rule versions, writes computed results, publishes events to outbox/queue.

- nginx (optional)
	- Responsibilities: HTTP reverse proxy, TLS termination, static assets.
	- Must Not Do: host application logic.

Configuration notes: do not store secrets in compose files. Environment classification: connection credentials (secrets), runtime flags (env), feature toggles (env), observability endpoints (env).

## 5. Extension Strategy (Future-proof)

- Any expansion MUST prefer adding new contexts or modules rather than changing Charter-level invariants.
- Examples:
	- Service modules (maintenance, inventory) should be implemented as new contexts or extensions that depend on Master/Core.
	- Add worker services (compute/import) as separate containers or profiles — never migrate core compute into synchronous core paths.
	- Expose analytics via read-only materialized views or a dedicated Analytics service consuming events.

## 6. Governance and Change Control

- Charter changes require a PR with a clear migration/compatibility plan.
- Breaking changes are allowed only with an explicit migration strategy and backward compatibility windows.
- Spec-first rule: specs updates MUST be created/approved prior to related code changes.

---

This file is the authoritative architecture-level specification (English). Feature-level specifications (002+) must reference this charter and comply with its hard rules.

