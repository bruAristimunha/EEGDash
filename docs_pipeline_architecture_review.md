# Docs-pipeline architecture review

Consolidated notes from three depth passes over `/Users/bruaristimunha/Projects/EEGDash` covering:

- Round 1 — how the documentation pages are generated end-to-end
- Round 2 — the API/data layer specifically (every fetch, every cache, every fallback)
- Round 3 — what `mongodb-eegdash-server` and `nemar-cli` already expose, and what could move server-side

Language used here follows `LANGUAGE.md`: **module**, **interface**, **depth**, **seam**, **leverage**, **locality**, **deletion test**.

---

## 1. The problem in one paragraph

The docs build talks to the EEGDash API through three independent paths, with five fallback levels, three caches, no retries, and silent failure on every step. The same logical resource (`/datasets/...`) is fetched 700+ times per build (mostly montages, N+1), and two of the calls go to near-duplicate endpoints (`/summary` and `/chart-data`) that each carry their own client-side handling. Most of the complexity is in the client; the server is well-shaped for our use case and has even shipped features the docs build hasn't adopted yet.

---

## 2. Current shape (what runs on a `make html`)

```
electrode-layouts step       1× GET /datasets/summary
                           + N× GET /datasets/{id}/montages   (≈700 calls, 8 workers)

prepare_summary_tables step  1× GET /datasets/summary  (force_refresh=True, bypasses disk cache)
                             1× GET /datasets/chart-data  (different endpoint, NO disk cache)
                             → writes eegdash/dataset/dataset_summary.csv (mutates the package!)
                             → writes summary_stats.json, search_index.json, chart HTMLs

sphinx-build step            ~1× call to fetch_datasets_from_api() at module import
                             + reads summary_stats.json on disk
                             + reads electrode-layouts.json on disk
                             + _generate_dataset_docs() writes 700+ ephemeral .rst files at build time
```

Three caches, all independent:

- `.eegdash_cache/dataset_summary.csv` — disk cache for `fetch_datasets_from_api`; not keyed by URL/database
- `_DATASET_SUMMARY_CACHE` — module-level global in `conf.py`; not keyed by URL/database
- `eegdash/dataset/dataset_summary.csv` — shipped with the package, *mutated by the build* via `_refresh_package_csv`

Five-level fallback when any fetcher is called:

```
in-memory cache → disk cache → live API → package CSV → empty dict (silent)
```

No retries, no backoff, 30s timeout, no `Cache-Control`/`ETag` headers on the server side.

---

## 3. Candidates

All candidates are listed once. Numbers are stable references; the execution order is in §4. Each lists: files involved, problem, solution, deletion-test result, benefits.

The three layers correspond to where the deepening happens:

- **Layer A** — server-side (mongodb-eegdash-server)
- **Layer B** — the data layer between server and docs (`eegdash.dataset.registry`, the snapshot)
- **Layer C** — Sphinx build internals (conf.py, RST scaffolding, templates)

---

### Layer A — server-side

#### A1. Use the `aggregations` block that `/datasets/chart-data` already returns

**Files.** `docs/plot_dataset/*.py`, `docs/prepare_summary_tables.py` (around l. 706, 731).

**Problem.** The chart-data endpoint already pre-computes `modality_counts`, `source_counts`, `pathology_counts`, `type_counts`, and `totals` server-side in a single pass. The client ignores them and recomputes the same numbers from row data, then each chart generator re-aggregates *again*. Three independent re-aggregations of the same dataset list. Whichever client disagrees is the bug.

**Solution.** Treat `aggregations` as the canonical totals; delete the client-side recomputation. The **module** that owns "what the counts are" is server-side.

**Deletion test.** Removing client-side aggregation moves zero behaviour — the server is already producing the numbers. Pure deletion win.

**Benefits.** One definition of every count. Same numbers in the docs, the homepage banner, the LLM tagger, any future consumer. Cost: zero on the server, ~50 LOC deleted on the client.

---

#### A2. `/build-manifest` endpoint — the missing provenance surface

**Files.** New endpoint on `mongodb-eegdash-server`. Consumed by `docs/prepare_summary_tables.py` and `conf.py`.

**Problem.** The docs build cannot tell apart "live API with 712 datasets" from "live API with 0 datasets because ingestion crashed" from "stale cache because the API is 503." The only way today to know "is this build healthy?" is to manually diff table HTML between builds. The memory note about silent-stale HTML traces directly to this.

**Solution.** A small endpoint:

```
GET /api/{db}/build-manifest →
{
  "dataset_count": 712,
  "last_ingested_at": "2026-05-18T06:00:00Z",
  "last_stats_computed_at": "2026-05-18T06:14:33Z",
  "schema_version": "2.1.0",
  "git_sha": "d61be9e",
  "name_coverage": 0.94
}
```

Docs build calls it at startup, logs it. CI gates on `dataset_count > 700 and name_coverage > 0.9`.

**Deletion test.** Without this, the client-side "tagged source" candidate (B2) is the wrong place to put provenance — only the server knows whether `dataset_count` represents a complete catalog. With this, B2 collapses to "trust the manifest."

**Benefits.** Provenance is one HTTP call away. Same endpoint feeds CI checks, Slack alerts, a "last updated" badge, future clients. ~40 LOC server-side; one new client call.

---

#### A3. `?include=montages` on `/datasets/chart-data` (kill the N+1)

**Files.** `mongodb-eegdash-server/api/main.py`; deprecates `docs/build_electrode_layouts.py` entirely.

**Problem.** Commit `5adb4d3` added `GET /api/{db}/datasets/{id}/montages` with a proper `$lookup` pipeline server-side — but that's still *per dataset*. The client still fires ≈700 HTTP calls with an 8-worker pool. Public rate limit is 30/min; this only works because docs build runs from a trusted IP.

**Solution.** Add `?include=montages` to `/datasets/chart-data`. One stage of `$lookup` joins the top montage per dataset into the existing aggregation. The client now does the whole "fetch all data for a docs build" in one HTTP call.

**Deletion test.** `build_electrode_layouts.py` (231 LOC, parallel fetcher, `--keep-existing-on-empty` flag, custom timeout handling) deletes entirely. Its complexity moves to one `$lookup` stage server-side.

**Benefits.** One round-trip per build. No rate-limit pressure. The `--keep-existing-on-empty` workaround disappears (it was patching the absence of B2).

---

#### A4. `Cache-Control` + `ETag` on read endpoints

**Files.** `mongodb-eegdash-server/api/main.py`. Current state: zero caching headers anywhere on the eegdash server. Compare `nemar-cli/backend/src/routes/data.ts` which already sets `max-age=60` on manifest/metadata.

**Problem.** Every docs build refetches the full chart-data payload (~5–10 MB) even when nothing has changed since the last build. No conditional GET possible. CDN caching impossible.

**Solution.** Add `Cache-Control: public, max-age=60` and an `ETag` (hash of the response body, or of `last_stats_computed_at`) to GET `/datasets/chart-data` and GET `/datasets/summary`. Client sends `If-None-Match`; on 304, reuse the cached parse.

This is mechanical — 10–30 lines per endpoint. Not architecturally deep, but pairs well with A2: together they enable "skip the whole build if `last_ingested_at` hasn't changed since the last snapshot on disk."

---

#### A5. Server-side chart-shape aggregations

**Files.** New endpoints on `mongodb-eegdash-server`. Collapses `docs/plot_dataset/{sankey,treemap,growth,bubble,clinical,kde}.py` (≈4715 LOC of mixed aggregation + rendering) to thin renderers.

**Problem.** Each chart generator receives the full DataFrame and does its own bucketing/sorting client-side. Sankey computes `(source → modality → count)`. Treemap computes `(source → modality → clinical → count)`. Growth sorts by `dataset_created_at` and accumulates. Each lives in its own Python module with its own version of the "canonical bucket."

**Solution.** Add server endpoints that return chart-shaped data:

```
GET /api/{db}/aggregations/sankey?levels=source,modality
GET /api/{db}/aggregations/treemap?path=source,modality,clinical
GET /api/{db}/aggregations/growth?bucket=month
GET /api/{db}/aggregations/bubble?x=subjects&y=files
```

The MongoDB pipeline lives in one place; `plot_dataset/*.py` collapses to "fetch JSON → hand to plotly," ~30 LOC each.

**Deletion test.** Aggregation logic moves from N client modules to one server **module** with direct access to indexes. Same operation, run where the data is.

**Benefits.** Locality (all "what does Sankey count?" answers in one pipeline). Leverage (notebooks, status pages, future LLM consumers all reuse the endpoints). Tests (pipeline testable against fixture MongoDB; today there are zero tests on the chart generators).

**Trade-off.** Highest server-side cost — 5–7 new routes. Worth it because each pipeline has high leverage beyond the docs.

---

#### A6. Dated/immutable snapshot endpoint

**Files.** New on `mongodb-eegdash-server`. Reuses the 24h scheduler that's already running (`a1b89c4`).

**Problem.** Today every docs build implicitly captures "the catalog as of the moment `make` ran." There's no way to ask "what did the catalog look like on 2026-04-01?" CI can't diff "what changed between this build and last week's" because the server only serves current state.

**Solution.** Have the 24h scheduler also write a daily snapshot:

```
GET /api/{db}/snapshots                 → list of {date, dataset_count, git_sha}
GET /api/{db}/snapshots/2026-05-18      → frozen chart-data response
GET /api/{db}/snapshots/latest          → alias
```

Each snapshot is content-addressable, never mutated, `Cache-Control: public, max-age=31536000, immutable`.

**Deletion test.** B1 (the snapshot module) becomes trivial — it just pins to `/snapshots/latest` and the manifest tells it what date that is.

**Benefits.** Reproducibility ("rebuild docs as of 2026-04-01"). Diff-friendly CI. Infinite cache lifetime. Reframes docs from "polling consumer of a live database" to "renderer of an immutable, dated artifact."

This is the boldest server-side candidate.

---

### Layer B — the data layer between server and docs

#### B1. Collapse client data access into a single `DatasetSnapshot` module

**Files.** `eegdash/dataset/registry.py:579–869` (the two near-duplicate fetchers `fetch_datasets_from_api` and `fetch_chart_data_from_api`); `docs/source/conf.py:419–437` (the unkeyed in-memory cache); `docs/prepare_summary_tables.py:1367, 1400, 1411` (three call sites); `docs/build_electrode_layouts.py:84, 98, 149`.

**Problem.** No canonical "the data this build is built from" object. Three fetchers, three caches, each invented locally. `fetch_datasets_from_api` and `fetch_chart_data_from_api` are near-duplicates — the chart-data one even falls back to `/datasets/summary` on 404. The `_DATASET_SUMMARY_CACHE` global in `conf.py` isn't keyed by `api_url` or `database`, so any future parameterization (staging vs prod) silently returns wrong data.

**Solution.** A deep **module** with a small **interface**:

```python
DatasetSnapshot.build(api_base, database) -> DatasetSnapshot   # one fetch, writes a manifest
DatasetSnapshot.load(manifest_path) -> DatasetSnapshot         # read what was built

  .rows() -> pd.DataFrame
  .aggregations() -> Aggregations
  .montage(dataset_id) -> Montage | None
  .source -> Literal["live", "cached", "package-csv"]
  .fetched_at -> datetime
  .dataset_count -> int
  .manifest -> BuildManifest         # see A2
```

Behind this **seam** lives the entire fetch/retry/cache/fallback story. `prepare_summary_tables.py`, `build_electrode_layouts.py` (or its replacement after A3), and `conf.py` all become consumers.

**Deletion test.** Delete the three fetchers and the unkeyed in-memory cache. Complexity *concentrates* into one place — exactly what we want. Today the same code is *replicated* across three call sites (each handling 4xx/5xx, empty-response, CSV fallback its own way).

**Benefits.** Locality (one file for "where does the data come from?"). Leverage (new consumers — future stats page, OG-image generator, sitemap timestamps — get the snapshot for free). Tests (mock `DatasetSnapshot.build` once; everything downstream becomes testable — this is the **test surface** that doesn't exist today).

---

#### B2. Tag failures rather than silently returning empty

**Files.** `eegdash/dataset/registry.py:619–620, 726–730, 781–784` (silent empty DataFrame); `docs/prepare_summary_tables.py:1368–1369` ("keeping existing CSV"); `docs/build_electrode_layouts.py:213–218` ("preserve last-good manifest").

**Problem.** Every API call's failure mode is the same: catch exception → return empty → caller logs a warning to stdout → build continues. No way for any consumer (or CI) to tell "API returned zero datasets" from "API down" from "we hit the cache." Build appears to succeed; artifact is silently degraded.

**Solution.** Lives *inside* B1's snapshot. Replace bare `pd.DataFrame()`-on-error returns with `source ∈ {"live", "cached", "package-csv"}`, plus `fetched_at`, `dataset_count`, `api_errors: list[str]`. Sphinx logs provenance once at startup. CI asserts `snapshot.source == "live" and snapshot.dataset_count > 700`.

**Deletion test.** This is not "add more error handling" — that adds shallow logic at every call site. It's the inverse: push policy decisions up to the build script, keep the snapshot honest about what it has.

**Benefits.** One place defines what "the build's data is healthy" means. Failure modes become testable. Pairs with A2 — once `/build-manifest` exists, the snapshot's `source` field flows directly from the server's report.

---

#### B3. Stop mutating the package CSV from the build

**Files.** `docs/prepare_summary_tables.py:1359, 1385` (`_refresh_package_csv` writes to `eegdash/dataset/dataset_summary.csv`); `eegdash/dataset/registry.py:157–328` (`register_openneuro_datasets` reads it at import); `conf.py:28–30` (Sphinx triggers that).

**Problem.** The package ships a `dataset_summary.csv`. The docs build mutates it during `prepare_summary_tables.py` so Sphinx imports see the same dataset list as the charts. This couples package state to docs-build state: a developer who runs `make html` locally gets a git-dirty package CSV (`M eegdash/dataset/dataset_summary.csv` shows in `git status` right now); tests using the package can't reproduce CI behaviour unless they also run the docs build; the package CSV is simultaneously a "static registry" *and* a "build cache."

**Solution.** Treat the package CSV as immutable static data (a registry snapshot taken at release time). The docs build's snapshot from B1 lives entirely under `docs/_build/` or `.eegdash_cache/` and never touches the package. `register_openneuro_datasets` reads the package CSV as before; the docs read the snapshot. They diverge intentionally.

**Deletion test.** Delete `_refresh_package_csv()`. Does anything actually break that wasn't a symptom of this coupling? Probably not: Sphinx already has its own dataset list via `_load_dataset_summary_from_api`. The CSV mutation existed to keep `register_openneuro_datasets`-time class generation in sync with table-time data — but the snapshot from B1 makes that alignment explicit and read-only.

**Benefits.** Package no longer carries build-time state. Two consecutive `make html` calls leave a clean working tree. Package tests stop being contaminated by docs-build artefacts.

---

#### B4. Content-addressable cache (defer until B1/B2/A2 land)

**Files.** `eegdash/dataset/registry.py:604–609, 726–730`; alongside the existing `docs/fingerprint_assets.py`.

**Problem.** The disk cache (`.eegdash_cache/dataset_summary.csv`) is a single file. No way to tell from looking at it which API URL it came from, when it was fetched, whether it's complete.

**Solution.** `DatasetSnapshot.build()` writes under a content-addressed name (`cache/snapshots/2026-05-18T14:33Z-abc123.json`) plus a `cache/snapshots/latest.json` pointer. Each snapshot embeds its provenance. Old snapshots can be diffed across builds.

Lowest priority — turns regressions into PR comments, but A6 (server-side dated snapshots) makes most of this irrelevant. Useful only if A6 doesn't ship.

---

### Layer C — Sphinx build internals

#### C1. Split `conf.py` event handlers into Sphinx extensions

**Files.** `docs/source/conf.py` (6047 LOC).

**Problem.** `conf.py` should be Sphinx config — a small **interface** declaring extensions and options. Instead it carries: ~1000 LOC of `_generate_dataset_docs` writing 700+ RST files at build time; `_inject_seo_context` building JSON-LD per page; `_copy_dataset_summary` post-copying artifacts; `_rewrite_sitemap_index`; `_write_auto_examples_root_index`; plus five RST templates defined as 80-line multi-line strings (l. 451–634). Handlers wired at the bottom (l. 5997–6010) — understanding *what* runs at build time requires reading the whole file.

**Solution.** Split each handler into its own Sphinx extension under `docs/source/_extensions/`, mirroring `dataset_explorer.py` (69 LOC, clean). `conf.py` shrinks to config + an `extensions = [...]` list.

**Benefits.** Locality (each concern in one file). Leverage (extensions can be turned on/off — fast docs builds can skip expensive page generation without commenting code). Tests (each extension testable with a mock Sphinx `app`).

---

#### C2. Replace `_generate_dataset_docs`'s RST-string generation with a directive

**Files.** `docs/source/conf.py:_generate_dataset_docs` (l. 4722–4850), `DATASET_PAGE_TEMPLATE` (l. 458–538).

**Problem.** The pipeline does: read CSV → render an RST string from a Python template → write 700+ ephemeral `.rst` files → Sphinx re-reads → parses → emits HTML. Two extra hops (string templating + disk I/O) that exist purely because the author didn't write a directive.

**Solution.** A `.. dataset-page::` directive that reads dataset metadata and emits docutils nodes directly. The existing `dataset_explorer.py` is a working precedent.

**Benefits.** HTML structure of a dataset page lives in one **module**, not in a `DATASET_PAGE_TEMPLATE` string with f-string interpolation across 80 lines. The five separate templates in `conf.py` collapse into one renderer. Renderer testable by invoking with a metadata dict and asserting on resulting nodes.

---

#### C3. Extract the 620-line DataTables JavaScript from `prepare_summary_tables.py`

**Files.** `docs/prepare_summary_tables.py` lines 722–1340.

**Problem.** ~620 lines of inline JS — sorting, column visibility, filter UX — live as a Python multi-line string. No syntax highlighting, no linting, no caching, no separation between table-data construction (Python) and table-UI behaviour (JS). The memory note about `th.cellIndex` vs internal column indices traces directly to debugging this JS inside a Python file.

**Solution.** Extract to `docs/source/_static/js/dataset_table.js` (real, lintable JS file) and `docs/source/_templates/dataset_table.html` (Jinja2 shell). `prepare_summary_tables.py` keeps only the responsibility of writing table-row HTML.

**Benefits.** Table-UI concerns become one JS file with proper tooling. Same JS reusable by the file-explorer or any future tabular view; today it's stuck in one Python function.

**Deletion test.** Deleting the inline template *concentrates* JS concerns into a real JS file (good signal — it was earning nothing by being inline).

---

#### C4. Consolidate `dataset_summary/*.rst`

**Files.** `docs/source/dataset_summary/{bubble,clinical,growth,kde,moabb,sankey,table,treemap}.rst` (189 LOC total).

**Problem.** Eight near-identical files — `<header>`, `<figure>`, `:file: ../_static/dataset_generated/dataset_XXXXX.html`, `<figcaption>` — varying only in title, caption, and embedded filename. Adding a ninth figure means copying a ninth file.

**Solution.** A `.. dataset-figure:: bubble` directive that takes the figure key and renders the scaffold around an embedded chart. Captions move into a single YAML/Python registry.

**Benefits.** Figure metadata in one registry instead of 8 files. Adding/removing/reordering figures becomes a one-line change.

Smallest candidate; lowest impact. Flagged for completeness.

---

## 4. Recommended execution order

The order is chosen so each step *makes the next one easier* and so the load-bearing changes land first.

| # | Candidate | Why this order |
|---|-----------|----------------|
| 1 | **A1** — adopt the `aggregations` block from chart-data | Zero server change; deletes client code; proves the chart-data response is enough |
| 2 | **A2** — `/build-manifest` endpoint | ~40 LOC server-side; unlocks B2's tagged-failure model |
| 3 | **A3** — `?include=montages` on chart-data | Retires `build_electrode_layouts.py` (231 LOC) entirely; one round-trip per build |
| 4 | **A4** — `Cache-Control` + `ETag` on read endpoints | Mechanical; pairs with A2 to enable "skip whole build if manifest unchanged" |
| 5 | **B1** — `DatasetSnapshot` module | All A-layer pieces now exist; the snapshot becomes the small **interface** behind which fetch/cache/fallback live |
| 6 | **B2** — tagged failures (folded into B1) | Falls out of B1 once A2's manifest is consumable |
| 7 | **B3** — stop mutating the package CSV | Mechanical follow-on; possible only once B1 owns the docs-build cache |
| 8 | **C1** — split `conf.py` into extensions | Independent of A/B; do whenever conf.py becomes painful again |
| 9 | **C2** — RST-generation → directive | Depends on C1's pattern being established |
| 10 | **C3** — extract DataTables JS | Independent; mechanical |
| 11 | **A5** — server-side chart aggregations | Highest payoff in client-code reduction but highest server cost; do once A1–A4 prove the pattern |
| 12 | **A6** — dated snapshots | The architectural deepener; reframes the catalog as a publishable artifact |
| 13 | **C4** — consolidate `dataset_summary/*.rst` | Lowest priority |
| —  | **B4** — content-addressed client cache | Likely irrelevant once A6 ships; skip unless A6 stalls |

---

## 5. End-state shape

After A1–A4 + B1–B3, the docs build's data layer is one function call:

```python
snapshot = DatasetSnapshot.fetch(api_base="data.eegdash.org/api")
# ─ 1 HTTP call (chart-data with ?include=montages, ETag-cached)
# ─ Server provenance via /build-manifest
# ─ source ∈ {"live", "cached", "package-csv"} surfaces failure mode
# ─ Snapshot lives entirely under docs/_build/; package CSV untouched
```

After A5, `plot_dataset/*.py` becomes a thin renderer over pre-aggregated JSON. After A6, the same snapshot can be pinned to a date and reproduced.

After C1–C2, `conf.py` is back to being Sphinx configuration — the event handlers and the 700+ ephemeral RST files are gone, replaced by directives that render dataset pages in place.

**Net effect:**

- ~700 HTTP calls per build → 1
- Three caches → one
- Five-level fallback → one tagged source
- Silent failures → loud and CI-gatable
- `git status` clean after `make html`
- `conf.py` ≈ 6047 LOC → ≈ 200 LOC
- `prepare_summary_tables.py` ≈ 1564 LOC → ≈ 400 LOC
- `build_electrode_layouts.py` ≈ 231 LOC → deleted
- `plot_dataset/*.py` ≈ 4715 LOC → ≈ 200 LOC of rendering

---

## 6. Notes on the wider landscape

- **`nemar-cli`/`data.nemar.org`** is already a mature HTTPS gateway with proper `Cache-Control`, ETag/Last-Modified, HEAD support, tombstone-aware 404s, and a per-dataset `metadata.json`. The docs build doesn't currently use it. The right boundary is: D1/data.nemar.org owns file-level state (size, mtime, BIDS index); MongoDB/eegdash-server owns catalog-level aggregations. Don't federate the docs build across both — stay with eegdash-server for the catalog.
- The **24-hour stats scheduler** on the eegdash server (commit `a1b89c4`) keeps per-dataset stats fresh. The docs build doesn't need to trigger `compute-stats` itself.
- **Phase 2 backfill** on nemar-cli ensures `enrichment_json` is populated for all public datasets, which in turn keeps the MongoDB catalog's `canonical_name`/`name_source`/`author_year` fields populated — the chart-data projection added in `bec765b` and `d61be9e` only became safe to rely on after that backfill.
- **No tests cover the docs build.** Every candidate in §3 either creates a testable **interface** as a side effect (B1, B2, A2, A5, C2) or removes code that doesn't need testing (A1, A3, B3, C3, C4). Coverage is a downstream benefit of the deepening, not a separate workstream.
