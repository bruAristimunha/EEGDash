# Test-Suite Semantic Merge + Comment Trim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Dispatch each Phase-1 task as a Sonnet subagent — the work is mechanical and bounded per file.

**Goal:** Per file, find sibling test functions that share a goal (same module under test, same shape of assertion, only the input/expected differs) and fold them into one parametrized test. While in each file, trim the docstrings down to a single useful sentence + the load-bearing context lines — drop the historical/PR-noise prose. Keep every assertion and every unique edge case.

**Architecture:** One subagent per file, dispatched against `record-enumerator-merge` HEAD. Each subagent reads its target file, identifies semantic groups, applies the parametrize transform, trims comments per the rules in this plan, runs that file's pytest selection, commits a single per-file commit. The orchestrator never touches code itself — it just dispatches + reviews.

**Tech Stack:** pytest 8.x `@pytest.mark.parametrize`, ruff (autofix).

---

## Pre-flight invariants the subagent should already see

* Branch is `record-enumerator-merge`; HEAD is `483f4157c` (or later).
* The reorg landed: tests live under `tests/{parsers,unit,digest,github,inject,pipeline,perf,acceptance}/` with `tests/_helpers/` for shared code. `INGEST_DIR` / `TESTS_DIR` come from `_helpers/__init__.py`.
* Run pytest with `EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache` from inside `scripts/ingestions/`.
* Lint is `ruff check tests/` from inside `scripts/ingestions/`. Auto-fix is allowed (`ruff check --fix tests/`).
* Pre-commit hooks reformat on commit — always re-stage + re-commit if the first commit gets rolled back.

---

## Universal rules every subagent MUST follow

### Merge rules (parametrize)

1. **Definition of "mergeable"**: a group of ≥3 sibling test functions where:
   - All call the same target (the function/class under test).
   - Each test differs only in input, expected output, or a single boolean flag.
   - The bodies have the same shape (same arrangement of arrange/act/assert).
2. **Merge format**: one parametrized function using `pytest.param(..., id="...")` rows; every former test name becomes a readable `id=`.
3. **Don't merge** tests that:
   - Have substantively different setup (different fixtures, different mocks, different file scaffolding).
   - Pin a distinct golden value that would be lost in a generic loop.
   - Carry a unique commentary block explaining a specific historical bug — keep that test standalone.
4. **Never delete an assertion.** If folding tests means losing one assert line, instead keep the test standalone.
5. **Test counts MUST stay equal or grow** after merging (parametrize expands rows back into individual test ids).

### Trim rules (docstrings + comments)

1. **First line of every docstring stays** (it's the headline shown in `pytest -v` output).
2. **Multi-paragraph docstrings**: collapse to the first sentence PLUS any lines that name a specific value, threshold, or non-obvious invariant.
3. **Drop forever**:
   - "Phase X / ROADMAP / SPRINT / PROGRESS" historical references.
   - "Was at N% coverage before this commit" — that's PR-noise, not test-time information.
   - "C1.5 covered the 3 HTTP-based adapters" — refers to a planning artifact that's gone.
   - Comments that restate what the code does (`# Loop through items`).
4. **Keep**:
   - Comments that explain WHY a specific value, tolerance, or invariant is what it is ("Allow 1% tolerance for linspace rounding").
   - Comments that document a non-obvious upstream contract ("MNE 1.12 raises AttributeError here when given a malformed FIF").
   - Section headers like `# ─── 1. Pure helpers ──────────────`.

### Output requirements (mandatory)

Every subagent reports back:
- The new commit SHA.
- Per-file `pytest` pass/skip count BEFORE and AFTER its changes (both must match or AFTER ≥ BEFORE).
- A one-line summary of what was merged + how much LOC was saved.

---

## Phase 1 — Per-file merge + trim (dispatch one Sonnet subagent each)

Dispatch all 13 Phase-1 tasks **sequentially** (avoid the parallel-worktree races that hit Phase-2 of the reorg plan). Each task has its own merge candidates listed inline.

### Task 1.1: `unit/test_stage_configs.py` (64 → ~30 tests)

**Files:**
- Modify: `scripts/ingestions/tests/unit/test_stage_configs.py`

**Merge candidates** (from grep audit):

| Group prefix | Count | Merge target |
|---|---|---|
| `test_clone_config_*` | 7 | Already partly parametrized; fold the remaining defaults / argv-flag tests. |
| `test_digest_config_*` | 8 | Defaults + bounds + env-var pickup matrix. |
| `test_inject_config_*` | 4 | Defaults + bounds matrix. |
| `test_validate_argv_*` | 4 | Argv parsing matrix. |
| `test_argv_parses_*` | 4 | Single argv-shape matrix. |
| `test_fetch_valid_*` | 6 | API-mock matrices (respx side_effects). |

- [ ] **Step 1: Run baseline**

```bash
cd scripts/ingestions
EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/unit/test_stage_configs.py -q --tb=line 2>&1 | tail -3
```

Record the count.

- [ ] **Step 2: For each group above, in-place replace the N sibling tests with one parametrized function**

Example pattern — for the `test_digest_config_*` defaults group, replace this shape:

```python
def test_digest_config_default_workers():
    c = DigestConfig(input=tmp_path)
    assert c.workers == 4

def test_digest_config_default_timeout():
    c = DigestConfig(input=tmp_path)
    assert c.timeout == DEFAULT_DATASET_TIMEOUT_SECONDS
```

with:

```python
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("workers", 4, id="workers"),
        pytest.param("timeout", DEFAULT_DATASET_TIMEOUT_SECONDS, id="timeout"),
        # ...one row per former test
    ],
)
def test_digest_config_defaults(tmp_path: Path, field: str, expected):
    """Documented field defaults."""
    c = DigestConfig(input=tmp_path)
    assert getattr(c, field) == expected
```

- [ ] **Step 3: Trim docstrings per the rules above**

For every test in the file, collapse multi-paragraph docstrings to the first useful sentence. Drop "Phase N" / "C1.5" / "before this commit" mentions.

- [ ] **Step 4: Run that file's pytest**

```bash
EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/unit/test_stage_configs.py -q --tb=line 2>&1 | tail -3
```

Expected: pass count ≥ baseline.

- [ ] **Step 5: Run ruff**

```bash
ruff check tests/unit/test_stage_configs.py
```

Expected: All checks passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/ingestions/tests/unit/test_stage_configs.py
git commit -m "test(stage_configs): merge sibling tests + trim docstrings

Folds 4 semantic groups of sibling tests (defaults / bounds /
env-pickup / argv-parsing matrices) into one parametrized function
each. Drops PR-noise references (Phase N / SPRINT-* / coverage
delta). Same total assertion count."
```

---

### Task 1.2: `unit/test_montage.py` (48 → ~28 tests)

**Files:**
- Modify: `scripts/ingestions/tests/unit/test_montage.py`

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_hash_sensors_*` | 5 | Determinism + order-invariance + sensitivity matrix. |
| `test_parse_coordsystem_*` | 5 | (missing / EEG / MEG / malformed / empty) parametrize. |
| `test_parse_sensor_*` | 5 | TSV parsing matrix (basic / n/a-rows / extras / missing-col / empty-name). |
| `test_parse_channels_*` | 5 | channels.tsv keep/skip matrix. |
| `test_score_template_*` | 5 | (best-overlap / empty / tied) matrix. |
| `test_walk_up_*` | 4 | BIDS-inheritance walk matrix. |

- [ ] Steps 1-6: same recipe as Task 1.1 with the file path swapped.

---

### Task 1.3: `digest/test_extraction_helpers.py` (43 → ~26 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_storage_base_*` | 7 | Storage URL per-source matrix. |
| `test_dep_keys_*` | 5 | dep_keys extraction matrix. |
| `test_storage_info_*` | 4 | storage_info per-source matrix. |
| `test_regular_record_*` | 3 | regular-record extraction matrix. |
| `test_is_bids_*` | 3 | is_bids matrix. |

- [ ] Steps 1-6: same recipe; pytest target `tests/digest/test_extraction_helpers.py`.

---

### Task 1.4: `digest/test_source_listing.py` (33 → ~20 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_local_bids_*` | 6 | Local-BIDS lister matrix (returns_empty / dir-vs-zip / dataset-zip). |
| `test_list_git_*` | 5 | git-files listing matrix. |
| `test_datarn_returns_*` | 3 | DataRN adapter matrix. |
| `test_all_adapters_*` | 3 | Cross-adapter contract matrix. |

- [ ] Steps 1-6: same recipe.

---

### Task 1.5: `unit/test_validate.py` (30 → ~18 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_validate_record_*` | 8 | (already 1 group parametrized; merge remaining storage-URL + missing-storage variants). |
| `test_validate_digestion_*` | 6 | Output-walker matrix (missing-dir / empty / walks / malformed-json / accepts-snapshot / strict-mode). |
| `test_validate_dataset_*` | 5 | accepts-minimal + warns-on-unknown + per-source matrix. |
| `test_storage_url_*` | 4 | Per-source canonical + cross-source mismatch matrix (some already parametrized). |

- [ ] Steps 1-6: same recipe.

---

### Task 1.6: `inject/test_helpers.py` (33 → ~20 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_load_records_*` | 5 | new-schema / bare-list / no-file / legacy-core / malformed matrix. |
| `test_load_montages_*` | 4 | envelope / bare-list / missing / null-payload matrix. |
| `test_sanitize_for_*` | 5 | (already 1 parametrize for NaN/Inf; fold the recurse-into-nested + recurse-into-lists + non-float-primitives into one matrix). |
| `test_flatten_entities_*` | 4 | (entities lift / top-level wins / no entities / no mutation) matrix. |
| `test_ensure_fingerprint_*` | 4 | seed-when-empty / preserve-existing / fallback / per-source matrix. |
| `test_find_digested_*` | 3 | digested-datasets-listing matrix. |

- [ ] Steps 1-6: same recipe.

---

### Task 1.7: `unit/test_http.py` (29 → ~16 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_request_json_*` | 10 | status-code + retry-policy matrix (200 / 404 / 502 / 503 / 408 / timeout / malformed JSON / custom-retry-statuses / retries=0 / raise_for_request). |
| `test_request_text_*` | 6 | text variant matrix (returns_text / 404 / timeout / raise_for_status / raise_for_request / 200). |
| `test_make_retry_*` | 4 | deprecation + authed-shape matrix. |
| `test_request_response_*` | 3 | response-variant matrix (raw / timeout / POST). |
| `test_build_headers_*` | 3 | header-construction matrix (accept / user-agent / extra-override). |

Note: respx decorators stack with `@pytest.mark.parametrize`. Place `@respx.mock` ABOVE `@pytest.mark.parametrize` so respx wraps each parametrize call independently.

- [ ] Steps 1-6: same recipe.

---

### Task 1.8: `digest/test_record_enumerator.py` (22 → ~13 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_write_outputs_*` | 7 | write-outputs matrix (dataset-file / records-file / montages-file / summary-file / json-shape / atomic / sort-order). |
| `test_has_actual_*` | 5 | _has_actual_recording_files matrix (has-files / no-files / has-symlink-but-broken / has-dir-but-empty / nested). |

- [ ] Steps 1-6: same recipe.

---

### Task 1.9: `digest/test_helpers.py` (17 → ~11 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_summarise_empty_*` | 5 | summarise-empty-or-error matrix (no-records / no-montages / both-empty / error-recorded / partial). |
| `test_parse_entities_*` | 4 | (already partly parametrized; absorb the per-field tests). |
| `test_check_skip_*` | 3 | skip-conditions matrix (existing-up-to-date / force / new). |

- [ ] Steps 1-6: same recipe.

---

### Task 1.10: `digest/test_bids_sidecar.py` (22 → ~13 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_sidecar_extracts_*` | 5 | power_line_freq / eeg_reference / software_filters / manufacturer+model / eeg_placement matrix. |
| `test_dataset_extras_*` | 5 | dataset-level sidecar matrix. |
| `test_channel_status_*` | 5 | channels.tsv status matrix (no-bad / counts-bad / case-insensitive / no-status-column / malformed-tsv). |
| `test_sidecar_handles_*` | 3 | error-handling matrix (missing / malformed-json / missing-attrs). |

- [ ] Steps 1-6: same recipe.

---

### Task 1.11: `unit/test_parser_utils.py` (26 → ~16 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_build_s3_*` | 5 | per-source URL build matrix (openneuro / nemar / url-encode / unknown-rejected / default-source). |
| `test_is_broken_*` | 4 | symlink classification matrix (real-file / broken / valid-link / missing). |
| `test_validate_file_*` | 4 | (real / missing / broken-symlink / dir) matrix. |
| `test_path_within_*` | 4 | (inside / outside / string-arg / self) matrix. |
| `test_extract_openneuro_*` | 3 | per-input matrix (returns-pair / nemar / unknown). |
| `test_read_encoding_*` | 3 | (utf8 / latin1 / missing) matrix. |

- [ ] Steps 1-6: same recipe.

---

### Task 1.12: `unit/test_file_utils.py` (25 → ~15 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_get_annex_*` | 8 | git-annex key-extraction matrix (regular-file / pointer / oversized / no-annex-path / target-exists / target-missing / ...). |
| `test_read_inline_*` | 7 | inline-sidecar reader matrix (oversized / non-allowlisted-ext / missing / regular / utf8 / latin1 / encoding-fallback). |
| `test_is_bids_*` | 6 | is_bids_root_file matrix (positive / negative / case / extension / hidden / nested). |
| `test_parse_annex_*` | 4 | annex-pointer-size matrix. |

- [ ] Steps 1-6: same recipe.

---

### Task 1.13: `unit/test_bids_paths.py` (29 → ~17 tests)

**Merge candidates:**

| Group prefix | Count | Merge target |
|---|---|---|
| `test_validate_structure_*` | 7 | (recognises-bids / rejects-non-bids / accepts-zips / requires-min-subjects / accepts-dataset-zip / include-files / files-limit) matrix. |
| `test_count_bad_*` | 6 | bad-channels-counter matrix (missing-file / no-bad / counts-bad / case / no-column / malformed-tsv). |
| `test_validate_from_*` | 3 | validate-from-files matrix (name-key / empty / missing-name). |
| `test_find_channels_*` | 3 | find-channels.tsv matrix (default / canonical / prefix-fallback). |

- [ ] Steps 1-6: same recipe.

---

## Phase 2 — Lint + final verification (sequential, orchestrator does this)

### Task 2.1: Full-suite verification

- [ ] **Step 1: Run the whole suite**

```bash
cd /Users/bruaristimunha/Projects/EEGDash/scripts/ingestions
EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/ -q -m "not network and not slow and not integration" --tb=line 2>&1 | tail -3
```

Expected: total pass count ≥ baseline at the start of Phase 1.

- [ ] **Step 2: ruff check + autofix**

```bash
ruff check --fix tests/
ruff check tests/
```

Expected: `All checks passed!`

- [ ] **Step 3: Push**

```bash
git push origin record-enumerator-merge
```

- [ ] **Step 4: Arm CI monitor on PR #354**

(Orchestrator armed an explicit Monitor task on the new HEAD.)

---

## Acceptance criteria

1. After Phase 1, every file in the Task 1.x list has fewer top-level `def test_*` definitions than before (verified by counting `def test_` per file).
2. Pytest pass count on the full suite is ≥ the pre-Task-1.1 baseline.
3. `ruff check tests/` reports "All checks passed!"
4. No assertion has been lost — search for any TODO / FIXME / `pass # was: ...` introduced by the merging process; there must be none.
5. Every former test-name appears in the new file either as a function name or as a `pytest.param(..., id="<former_name>")` row.
6. CI passes on PR #354.

---

## Out-of-scope

* Adding new test coverage — this is a refactor, not a coverage push.
* Re-organising any test file's location (we just did that in the reorg PR; layout is stable).
* Editing test files NOT in the Task 1.x list (the remaining ~34 files are either already lean or don't have ≥3 sibling groups).
* Editing fixture builders in `_helpers/` (they are stable, used by many tests).
