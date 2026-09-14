# EcomInsight implementation status

Updated: 2026-09-14

## Implemented and tested

- Upstream license, required notice and attribution retained.
- CSV/XLSX Streamlit workflow with sheet selection and field confirmation.
- E-commerce field semantic mapping and contract models.
- Versioned metric registry with filters, derived metrics and dependency checks.
- Data Health Score, issue details and blocking quality gate.
- Structured, allowlisted analysis plans with ambiguity and injection safeguards.
- GMV comparison, KPI driver-tree decomposition and dimension contribution drill-down.
- RFM, ordered funnel, Cohort, repurchase and product-performance analysis APIs.
- Analysis Run state, stable hashes, configuration snapshots and replay input checks.
- Evidence, Claims, causal-language gate and self-contained HTML report.
- GitHub Actions, static checks, unit tests and end-to-end run test.

## Deliberately deferred

These items are Optional or V3 enhancements in `PROJECT_PLAN.md` and do not block the core portfolio release:

- DuckDB and million-row benchmarks.
- MySQL connection.
- Docker image.
- Advanced PII/NLP detection.
- Production authentication, authorization and multi-tenancy.

No performance numbers are claimed before a reproducible benchmark is implemented.
