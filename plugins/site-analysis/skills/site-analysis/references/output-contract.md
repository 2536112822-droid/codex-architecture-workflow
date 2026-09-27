# Output contract

Each full `analyze_site.py` invocation writes to `<out-dir>/runs/<run-id>/`; cache files live outside the run directory. This full-package contract does not require running the pipeline for a factual query or a scoped revision. Scoped revisions retain their source run, evidence, and separate output version. Never infer the current result by scanning an output directory. Read `<out-dir>/latest.json`, then verify that run's `manifest.json`.

## Required artifacts

| Artifact | Purpose |
|---|---|
| `00_analysis_board.png/svg/pdf` | Presentation overview and visual QA |
| `01`–`06` diagram sets | Editable/vector and raster source panels |
| `site_analysis_report.json` | Counts, bounds, terrain summary and output index |
| `quality_report.json` | Machine-readable pass/warn/fail checks |
| `provenance.json` | Inputs, CRS, request metadata, source hashes |
| `manifest.json` | Exact files and SHA-256 hashes for this run |

`provenance.json` records OSM `layer_status` separately from feature counts:
`available`, `empty` (a successful zero-row return), `no_matches` (OSMnx reports no
matching features, but may have discarded an upstream error remark), `unavailable`, `skipped`, or
`unknown` for older inputs without status. `no_matches` leaves upstream completeness
unknown; neither it nor an empty result proves real-world absence.
Query `accessed_at_utc` is the local load time, including possible OSMnx cache
reads. The retained `retrieved_at_utc` field is a legacy alias, not proof of a new
network fetch. `source_observed_at_utc: null` and `cache_status: unknown` must not
be converted into an age or freshness claim.

Elevation `observed_finite_fraction` measures valid sampled DEM cells before
filling; `interpolated_fraction` records cells filled by the existing nearest
interpolation. The legacy `finite_fraction` still describes the final grid.
Coverage QA uses the original fraction; older grids without it report source
coverage as unknown. These fractions describe the sampled grid, not survey
accuracy or completeness of real-world terrain.

## Acceptance

1. No check may be `fail`.
2. Every `warn` must be stated to the user; an unavailable layer must remain visibly unavailable.
3. Study extent and legal/site boundary must use different line styles and labels.
4. Inspect the board PNG at readable size before delivery; JSON success alone is insufficient.
5. Keep separate staged runs during work for comparison. At closeout follow the current global save and retention policy and this task's authorization; shared caches are outside task cleanup. Deliver the required results at the specified or confirmed location, without archiving every revision, and update manifests and references for the delivered subset.
