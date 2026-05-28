# Test Suite Parametrization Simplification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or work sequentially in-session. Each task in Phase 2 is independent of the others, so they can run in parallel when dispatched via `isolation: "worktree"`.

**Goal:** Cut the ingestion test suite's line count by 20-30% by folding the repetitive "same shape, different input" tests into `@pytest.mark.parametrize`. Target high-value files identified by the audit at the bottom of this document. Keep every assertion; don't collapse tests that have genuinely distinct setup/teardown.

**Architecture:** Per file, identify groups of tests that share a function body skeleton (same setup, same assertion shape, only the input/expected differs). Replace the group with one parametrized function + a `params = [...]` list. Drop tests that no longer carry information after the merge (e.g., 3 separate tests asserting the same thing on `int` / `float` / `Decimal` collapse to one parametrize over the type set).

**Tech Stack:** pytest 8.x `@pytest.mark.parametrize` and `pytest.param(..., id=...)`.

---

## Pre-flight invariants

* Branch `record-enumerator-merge` HEAD is `56a909cb7`.
* The reorg landed: tests now live under `tests/{parsers,unit,digest,github,inject,pipeline,perf,acceptance}/` with `tests/_helpers/` for shared code.
* The pytest suite passes: `EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -m pytest scripts/ingestions/tests/ -q -m "not network and not slow and not integration"` returns 866 passed / 2 skipped.
* Use that exact pytest invocation to verify each task — every parametrization must keep the pass count constant.

---

## Phase 0 — Lock the baseline (sequential)

### Task 0.1: Record the pre-parametrization test count

- [ ] **Step 1: Capture baseline**

```bash
cd /Users/bruaristimunha/Projects/EEGDash/scripts/ingestions
EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/ -q -m "not network and not slow and not integration" 2>&1 \
  | tail -3 \
  | tee /tmp/parametrization-baseline.txt
```

Expected: `XYZ passed, 2 skipped, ZZ deselected, NN warnings in TT.TTs`. The XYZ + 2 skipped totals must match at the end of Phase 3.

---

## Phase 2 — Per-file parametrization (PARALLEL — independent)

Each task touches exactly one file. They can be dispatched in parallel via subagent worktrees if desired, since they don't share state.

For each task:
1. Read the target file.
2. Identify groups of 4+ tests with shared body shape.
3. Replace each group with `@pytest.mark.parametrize` + a `params = [pytest.param(..., id="..."), ...]` list. Use descriptive `id=` so the failure output stays readable.
4. Run the file's tests; pass count for the file must be ≥ pre-merge count (parametrize cases count individually).
5. Run `ruff check tests/` — must pass.
6. Commit.

### Task 2.1: `tests/unit/test_stage_configs.py` (66 → ~25 tests)

**Target groups (extract from the merged file's three sections):**
* "Field X loads default" tests across the three config classes — fold into one parametrized test over `(config_cls, field, default_value)` triples.
* "Field X overrides via env var" tests — one parametrized test over `(config_cls, field, env_name, env_value, expected)`.
* "Invalid value raises ValidationError" tests — parametrize over `(field, bad_value)`.

**Pattern to apply** (illustrative — substitute real field names):

Before:
```python
def test_clone_max_workers_default():
    cfg = CloneConfig()
    assert cfg.max_workers == 8

def test_clone_timeout_default():
    cfg = CloneConfig()
    assert cfg.timeout_seconds == 300

# ... 6 more "default" tests for the same config
```

After:
```python
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("max_workers", 8, id="max_workers=8"),
        pytest.param("timeout_seconds", 300, id="timeout=300"),
        # ...
    ],
)
def test_clone_config_loads_default(field, expected):
    cfg = CloneConfig()
    assert getattr(cfg, field) == expected
```

- [ ] Verify: `pytest tests/unit/test_stage_configs.py -q` passes; total case count (incl. parametrize expansion) ≥ 66.
- [ ] Commit: `test(stage_configs): parametrize repeated default/override/invalid groups`

### Task 2.2: `tests/unit/test_montage.py` (49 → ~30 tests)

**Target groups (from the three sections):**
* `_hash_sensors` / `_round_mm` / `_score_template_match` — small pure helpers with multiple input/output pairs. Parametrize.
* `_parse_channels_tsv_for_eeg` shape tests — parametrize over (tsv content, expected channels).
* `_walk_up_find` directory inheritance — parametrize over (start_dir, target_filename, expected_match).

- [ ] Verify: `pytest tests/unit/test_montage.py -q` passes.
- [ ] Commit: `test(montage): parametrize repeated helper invariants`

### Task 2.3: `tests/unit/test_serialize.py` (34 → ~18 tests)

**Likely group:**
* "Field X round-trips via JSON" — parametrize over field names.
* "Type X serialises to expected representation" — parametrize over (input, expected_json).

- [ ] Verify: `pytest tests/unit/test_serialize.py -q` passes.
- [ ] Commit: `test(serialize): parametrize round-trip + representation tests`

### Task 2.4: `tests/unit/test_http.py` (29 → ~15 tests)

The file already has the `_no_cache_env` fixture. Heavy parametrization opportunity:
* "Status N is retried / not retried" — parametrize over (status_code, retried).
* "Request method X with body Y" — parametrize over (method, body, expected).

But: respx mock setup may differ per case; verify the parametrize pattern doesn't make individual tests harder to debug. If a test has a unique mock side-effect, keep it standalone.

- [ ] Verify: `pytest tests/unit/test_http.py -q` passes.
- [ ] Commit: `test(http): parametrize status-code + method matrices`

### Task 2.5: `tests/unit/test_bids_paths.py` (29 → ~16 tests)

**Likely groups:**
* BIDS inheritance walk: parametrize over (file_path, ancestor_files, expected_resolved).
* Entity-extraction shape: parametrize over (path, entity_dict).

- [ ] Verify: `pytest tests/unit/test_bids_paths.py -q` passes.
- [ ] Commit: `test(bids_paths): parametrize inheritance + entity extraction matrices`

### Task 2.6: `tests/unit/test_file_utils.py` (25 → ~15 tests)

**Likely groups:**
* Path-tolerance edge cases: parametrize over (input_path_form, expected_resolution).
* Permission / OS error handling: parametrize over (raised_exception, expected_return).

- [ ] Verify: `pytest tests/unit/test_file_utils.py -q` passes.
- [ ] Commit: `test(file_utils): parametrize edge-case matrices`

### Task 2.7: `tests/unit/test_parser_utils.py` (27 → ~16 tests)

**Likely groups:**
* `path_is_within_root` boundary cases — parametrize over (candidate, root, expected).
* Path-string normalisation — parametrize over (input, normalised).
* Type-coercion helpers — parametrize over (raw, expected_typed).

- [ ] Verify: `pytest tests/unit/test_parser_utils.py -q` passes.
- [ ] Commit: `test(parser_utils): parametrize coercion + boundary matrices`

### Task 2.8: `tests/unit/test_validate.py` (34 → ~20 tests)

Already has 3 parametrized groups; pull more in.
* "VALID_STORAGE_PATTERNS accepts source X" — parametrize over the dict keys.
* "Storage URL with wrong source surfaces error" — parametrize over (source, url, expected_error).
* Missing-recommended-field warnings — parametrize over field names.

- [ ] Verify: `pytest tests/unit/test_validate.py -q` passes.
- [ ] Commit: `test(validate): parametrize per-source + per-field matrices`

### Task 2.9: `tests/parsers/test_set.py` (25 → ~16 tests)

* The synthetic-MAT v5 section has 6 tests that build a fixture with different `srate`/`nbchan`/`pnts` and assert on the same field. Parametrize over the field+value pairs.
* Edge-case garbage inputs: already partially parametrized; pull in the few that aren't.

- [ ] Verify: `pytest tests/parsers/test_set.py -q` passes.
- [ ] Commit: `test(set): parametrize synthetic-fixture matrix`

### Task 2.10: `tests/parsers/test_vhdr.py` (19 → ~12 tests)

The file already has 1 parametrize. Likely candidates:
* "Channel name at index X is Y" — parametrize over (idx, expected_name) (currently 5 separate cases).
* "Diagnose-vhdr reports field Z" — parametrize over field names.
* Garbage-input tolerance — parametrize over input bytes.

- [ ] Verify: `pytest tests/parsers/test_vhdr.py -q` passes.
- [ ] Commit: `test(vhdr): parametrize channel-index + diagnose matrices`

### Task 2.11: `tests/parsers/test_mef3.py` (12 → ~9 tests)

Two synthetic-mefd tests with different channel sets — parametrize over `(channels, expected_nchans, expected_first_name)`.

- [ ] Verify: `pytest tests/parsers/test_mef3.py -q` passes.
- [ ] Commit: `test(mef3): parametrize channel-set + truncation matrices`

### Task 2.12: `tests/parsers/test_snirf.py` (14 → ~10 tests)

`_build_synthetic_snirf` is called with different `n_channels` / `include_probe_labels` — parametrize.

- [ ] Verify: `pytest tests/parsers/test_snirf.py -q` passes.
- [ ] Commit: `test(snirf): parametrize synthetic-HDF5 matrices`

### Task 2.13: `tests/unit/test_rate_limited.py` (9 → ~5 tests)

All 9 tests share a single-prefix shape. Almost certainly all parametrizable.

- [ ] Verify: `pytest tests/unit/test_rate_limited.py -q` passes.
- [ ] Commit: `test(rate_limited): parametrize decorator behaviour matrix`

### Task 2.14: `tests/unit/test_metadata_provenance.py` (12 → ~7 tests)

Likely a per-record-type matrix.

- [ ] Verify: `pytest tests/unit/test_metadata_provenance.py -q` passes.
- [ ] Commit: `test(metadata_provenance): parametrize per-record-type matrix`

### Task 2.15: `tests/pipeline/test_clone_error_handling.py` (6 → ~3 tests)

All 6 tests share one prefix. Likely parametrizable over (failure_kind, expected_handling).

- [ ] Verify: `pytest tests/pipeline/test_clone_error_handling.py -q` passes.
- [ ] Commit: `test(clone_error_handling): parametrize failure-class matrix`

---

## Phase 3 — Final verification (sequential)

### Task 3.1: Full pytest sweep + push

- [ ] **Step 1: Run the full suite**

```bash
cd /Users/bruaristimunha/Projects/EEGDash/scripts/ingestions
EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/ -q -m "not network and not slow and not integration" 2>&1 \
  | tail -3
```

Expected: same `XYZ passed, 2 skipped, 20 deselected` as the Phase 0 baseline. **Crucial**: parametrize expansion may add expanded test IDs but the assertion count must match.

- [ ] **Step 2: Diff stats — confirm LOC reduction**

```bash
git diff origin/develop...HEAD --stat scripts/ingestions/tests/ | tail -3
```

The "tests/" portion of the PR should now show **net negative** lines compared to the pre-parametrization HEAD.

- [ ] **Step 3: Push**

```bash
git push origin record-enumerator-merge
```

---

## Acceptance criteria

* `python -m pytest tests/ -m "not network and not slow and not integration"` returns the same pass + skip totals as the Phase 0 baseline (parametrize cases count individually — totals match).
* `ruff check tests/` reports "All checks passed!"
* Net line delta across `scripts/ingestions/tests/` is negative versus pre-Task-2.1 HEAD.
* No test functionality is lost: every former test name is reachable via the new parametrize `id=` or remains as a standalone test.

---

## Audit data (snapshot at plan-write time)

```
file                                     n_tests  parametrized  largest-shared-prefix
unit/test_stage_configs.py                    66             0                      8
unit/test_montage.py                          49             0                      5
unit/test_serialize.py                        34             0                      6
unit/test_validate.py                         34             3                     11
unit/test_http.py                             29             0                     10
unit/test_bids_paths.py                       29             0                      7
unit/test_parser_utils.py                     27             0                      5
unit/test_file_utils.py                       25             0                      8
parsers/test_set.py                           25             1                     15
parsers/test_vhdr.py                          19             1                     14
unit/test_parser_utils_network.py             19             0                      6
parsers/test_snirf.py                         14             1                      6
parsers/test_mef3.py                          12             1                      7
unit/test_metadata_provenance.py              12             0                      4
unit/test_path_traversal.py                   11             0                      5
unit/test_rate_limited.py                      9             0                      9
inject/test_api_calls.py                       8             0                      4
pipeline/test_schema_preflight.py              7             1                      4
pipeline/test_clone_error_handling.py          6             0                      6
```

Files NOT targeted (already parametrized or genuinely orthogonal tests): everything not in the table above.

---

## Out-of-scope

* Rewriting tests that have substantively different setup/teardown — keep those standalone.
* Adding new tests — this is a refactor, not a coverage push.
* Touching tests/acceptance/* — those are integration contracts that already follow a different shape.
