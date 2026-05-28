# Test Suite Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Phase-2 tasks (2.1–2.7) are independent of each other and SHOULD be dispatched in parallel — one subagent per subfolder.

**Goal:** Cut `scripts/ingestions/tests/` from 57 flat files (~15.4 KLOC) down to ~40 files organized into 8 topical subfolders, with shared synthetic builders in `_helpers/`, and the JSON I/O snapshot corpus relocated from inline `tests/fixtures/digest_snapshots/` to the `eegdash-testing-data` repo. Also unblock the active CI failure (`tests/test_perf.py` was missed in the prior fixture migration).

**Architecture:** Tests are organised by *what shape of test* (parser, unit, digest, pipeline, perf, inject, github, acceptance), not by what source module they cover. The repo-wide path bootstrap and `data_path()` skip-on-failure logic live in one root `conftest.py` so subfolder tests inherit it automatically. Three currently-duplicated synthetic-fixture builders move to `tests/_helpers/builders.py`. The digest-snapshot JSON fixtures (~180 KB, 25 files) move to a versioned `eegdash-testing-data` release that `eegdash.testing.data_path()` already manages.

**Tech Stack:** pytest 8.x, pooch 1.7+ (existing), pytest-benchmark, hypothesis, `eegdash.testing.data_path/data_file` (added earlier in this PR).

---

## Pre-flight invariants the engineer should already see

* PR #354 branch is `record-enumerator-merge`.
* The `eegdash/eegdash-testing-data` repo exists at `https://github.com/eegdash/eegdash-testing-data` with tag `v0.1.0` shipping `eeg/`, `fnirs/`, `ieeg/`, `meg/` corpora.
* `eegdash/testing.py` already exposes `data_path() / data_file(relpath) / requires_testing_data / has_testing_data()`. The current SHA-256 pinned in that file is `bf7303148bf4acab2b51ad69adc76574360ac096bf29b5a76b510ad77981bbae`.
* `scripts/ingestions/tests/conftest.py` already inserts the ingestion directory into `sys.path` for the whole tree. The 45 individual test files that still re-do that dance can drop those lines safely.
* The active CI red on commit `5ce81da2b` is exactly one test: `tests/test_perf.py::test_parse_vhdr_median_under_5ms` — it hard-codes `Path(__file__).parent / "fixtures" / "eeg" / "sub-xp101_task-motorloc_eeg.vhdr"` which no longer exists.

---

## Phase 0 — CI hotfix (sequential, must land first)

### Task 0.1: Migrate `test_perf.py` to `data_file()` + fix scrubber typo

**Files:**
- Modify: `scripts/ingestions/tests/test_perf.py:24-29` (replace hard-coded path), `:56` (fix "copy.md" leftover from earlier scrub)

- [ ] **Step 1: Read the file to confirm current shape**

Run: `sed -n '24,32p' scripts/ingestions/tests/test_perf.py`
Expected: `EEG_VHDR = Path(__file__).parent / "fixtures" / "eeg" / "sub-xp101_task-motorloc_eeg.vhdr"` on or near line 27.

- [ ] **Step 2: Replace fixture path resolution**

In `scripts/ingestions/tests/test_perf.py`, replace:

```python
from _fingerprint import fingerprint_from_manifest
from _vhdr_parser import parse_vhdr_metadata

EEG_VHDR = (
    Path(__file__).parent / "fixtures" / "eeg" / "sub-xp101_task-motorloc_eeg.vhdr"
)
```

with:

```python
from eegdash.testing import data_file

from _fingerprint import fingerprint_from_manifest
from _vhdr_parser import parse_vhdr_metadata

EEG_VHDR = data_file("eeg/sub-xp101_task-motorloc_eeg.vhdr")
```

- [ ] **Step 3: Fix the orphan "copy.md" from the prior scrub**

In the same file replace:

```python
        f"forgotten copy.md § Phase 7."
```

with:

```python
        f"forgotten copy."
```

- [ ] **Step 4: Run the failing test**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/test_perf.py::test_parse_vhdr_median_under_5ms -q --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit + push**

```bash
git add scripts/ingestions/tests/test_perf.py
git commit -m "fix(tests): migrate test_perf.py to data_file() + scrub leftover"
git push origin record-enumerator-merge
```

---

## Phase 1 — Foundation (sequential — these tasks must land in order)

### Task 1.1: Mirror `digest_snapshots/` into `eegdash-testing-data` + bump to v0.2.0

**Files:**
- Source (read-only): `scripts/ingestions/tests/fixtures/digest_snapshots/**` (25 files, ~180 KB)
- Destination (NEW): `/tmp/eegdash-testing-data/digest_snapshots/**`
- Modify: `eegdash/testing.py:34-35` (pin version + sha)

- [ ] **Step 1: Refresh the testing-data clone**

```bash
rm -rf /tmp/eegdash-testing-data
git clone https://github.com/eegdash/eegdash-testing-data /tmp/eegdash-testing-data
cd /tmp/eegdash-testing-data && git status --short
```

Expected: clean working tree on `main`.

- [ ] **Step 2: Copy the snapshot corpus into the clone**

```bash
SRC=/Users/bruaristimunha/Projects/EEGDash/scripts/ingestions/tests/fixtures/digest_snapshots
DST=/tmp/eegdash-testing-data/digest_snapshots
mkdir -p "$DST"
cp -r "$SRC/." "$DST/"
cd /tmp/eegdash-testing-data && find digest_snapshots -type f | wc -l
```

Expected: `25`.

- [ ] **Step 3: Commit + tag v0.2.0 in the testing-data repo**

```bash
cd /tmp/eegdash-testing-data && \
  git -c user.email=b.aristimunha@gmail.com -c user.name=Bru add digest_snapshots && \
  git -c user.email=b.aristimunha@gmail.com -c user.name=Bru commit -m "add digest_snapshots corpus (JSON I/O contracts for stage-3 ↔ stage-5)" && \
  git -c user.email=b.aristimunha@gmail.com -c user.name=Bru tag -a v0.2.0 -m "v0.2.0 — adds digest_snapshots/ corpus" && \
  git push origin main && \
  git push origin v0.2.0
```

Expected output ends with: `* [new tag] v0.2.0 -> v0.2.0`.

- [ ] **Step 4: Compute the new tarball SHA-256**

```bash
curl -sL https://codeload.github.com/eegdash/eegdash-testing-data/tar.gz/refs/tags/v0.2.0 | shasum -a 256
```

Expected: a 64-hex-character string. Record it.

- [ ] **Step 5: Update the pin in `eegdash/testing.py`**

Replace these two lines:

```python
VERSION = "0.1.0"
SHA256 = "bf7303148bf4acab2b51ad69adc76574360ac096bf29b5a76b510ad77981bbae"
```

with (substituting the SHA recorded in step 4):

```python
VERSION = "0.2.0"
SHA256 = "<SHA-256 FROM STEP 4>"
```

- [ ] **Step 6: Smoke-test the fetch path against a fresh cache**

```bash
rm -rf /tmp/eegdash-test-cache
EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -c "
from eegdash.testing import data_path
root = data_path()
print('root:', root)
ds = root / 'digest_snapshots' / 'inputs' / 'ds_snapshot_vhdr' / 'dataset_description.json'
print('exists:', ds.exists())
"
```

Expected: `root: /tmp/eegdash-test-cache/eegdash-testing-data-0.2.0` followed by `exists: True`.

- [ ] **Step 7: Commit the pin bump in eegdash repo**

```bash
cd /Users/bruaristimunha/Projects/EEGDash
git add eegdash/testing.py
git commit -m "chore(testing): bump eegdash-testing-data pin to v0.2.0 (adds digest_snapshots)"
```

---

### Task 1.2: Extend `tests/conftest.py` to expose `digest_snapshots_dir` fixture

**Files:**
- Modify: `scripts/ingestions/tests/conftest.py` (add one fixture)

- [ ] **Step 1: Add the fixture**

Append to `scripts/ingestions/tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def digest_snapshots_dir() -> Path:
    """Directory containing digest_snapshots/{inputs,outputs}/ds_snapshot_*."""
    return _testing_data_root() / "digest_snapshots"
```

- [ ] **Step 2: Update `FIXTURES_DIR` comment**

In the same file, replace:

```python
FIXTURES_DIR = Path(__file__).parent / "fixtures"  # JSON snapshots stay inline
```

with:

```python
FIXTURES_DIR = Path(__file__).parent / "fixtures"  # only inline: records/
```

- [ ] **Step 3: Verify fixture resolves**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -c "
import pytest, sys
sys.path.insert(0, 'tests')
from conftest import _testing_data_root
print('digest_snapshots_dir:', _testing_data_root() / 'digest_snapshots')
"
```

Expected: a path ending in `eegdash-testing-data-0.2.0/digest_snapshots`.

- [ ] **Step 4: Commit**

```bash
git add scripts/ingestions/tests/conftest.py
git commit -m "test(conftest): expose digest_snapshots_dir fixture from testing-data"
```

---

### Task 1.3: Update every consumer of `digest_snapshots` to use the fixture

**Files (10 consumers):**
- Modify: `scripts/ingestions/tests/test_digest_snapshot.py`
- Modify: `scripts/ingestions/tests/test_inject_api_calls.py`
- Modify: `scripts/ingestions/tests/test_perf.py`
- Modify: `scripts/ingestions/tests/test_pipeline_invariants.py`
- Modify: `scripts/ingestions/tests/test_bids_sidecar_enrichment.py`
- Modify: `scripts/ingestions/tests/test_validate_functions.py`
- Modify: `scripts/ingestions/tests/test_digest_telemetry.py`
- Modify: `scripts/ingestions/tests/test_pipeline_e2e.py`
- Modify: `scripts/ingestions/tests/test_metadata_provenance.py`
- Modify: `scripts/ingestions/tests/acceptance/conftest.py`

- [ ] **Step 1: List every reference**

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  grep -rn "digest_snapshots" scripts/ingestions/tests/ --include="*.py"
```

For each line that contains `Path(...) / "fixtures" / "digest_snapshots"` or `FIXTURES_DIR / "digest_snapshots"`, replace with the `digest_snapshots_dir` fixture (function-arg) or a direct `data_file("digest_snapshots/...")` call.

- [ ] **Step 2: Use `data_file("digest_snapshots/...")` for module-level constants**

Pattern: where a test file currently has at module scope:

```python
_SNAPSHOT_OUTPUTS = Path(__file__).parent / "fixtures" / "digest_snapshots" / "outputs"
```

replace with:

```python
from eegdash.testing import data_file

_SNAPSHOT_OUTPUTS = data_file("digest_snapshots/outputs")
```

- [ ] **Step 3: Update `acceptance/conftest.py`**

In `scripts/ingestions/tests/acceptance/conftest.py`, replace:

```python
_SNAPSHOT_OUTPUTS = _INGEST_DIR / "tests" / "fixtures" / "digest_snapshots" / "outputs"
```

with:

```python
from eegdash.testing import data_file

_SNAPSHOT_OUTPUTS = data_file("digest_snapshots/outputs")
```

- [ ] **Step 4: Run the affected tests**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest \
    tests/test_digest_snapshot.py tests/test_inject_api_calls.py tests/test_perf.py \
    tests/test_pipeline_invariants.py tests/test_bids_sidecar_enrichment.py \
    tests/test_validate_functions.py tests/test_digest_telemetry.py \
    tests/test_pipeline_e2e.py tests/test_metadata_provenance.py \
    tests/acceptance/ \
    -q --tb=line
```

Expected: all PASS.

- [ ] **Step 5: Delete the on-disk inline `digest_snapshots/`**

```bash
git rm -r scripts/ingestions/tests/fixtures/digest_snapshots/
```

- [ ] **Step 6: Re-run the same test selection to confirm tests now read from the cached corpus**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest \
    tests/test_digest_snapshot.py tests/test_inject_api_calls.py tests/test_perf.py \
    tests/test_pipeline_invariants.py tests/test_bids_sidecar_enrichment.py \
    tests/test_validate_functions.py tests/test_digest_telemetry.py \
    tests/test_pipeline_e2e.py tests/test_metadata_provenance.py \
    tests/acceptance/ \
    -q --tb=line
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add -A scripts/ingestions/tests/
git commit -m "test: migrate digest_snapshots consumers to eegdash.testing.data_file()

10 test files were resolving digest_snapshots paths inline via
Path(__file__).parent / 'fixtures' / 'digest_snapshots'. Move them
to data_file() so the corpus lives once in eegdash-testing-data v0.2.0."
```

---

### Task 1.4: Create `_helpers/` package + extract three synthetic builders

**Files:**
- Modify: `scripts/ingestions/tests/conftest.py` (add `tests/` itself to sys.path so `from _helpers.builders import ...` resolves from any subfolder)
- Create: `scripts/ingestions/tests/_helpers/__init__.py` (1 line)
- Create: `scripts/ingestions/tests/_helpers/builders.py` (~130 LOC, three functions copied verbatim from their current homes)
- Modify: `scripts/ingestions/tests/test_set_happy_path.py` (delete the local `_build_synthetic_set_v5`, import from `_helpers.builders`)
- Modify: `scripts/ingestions/tests/test_mef3_real_fixture.py` (delete the local `_build_mefd_around_real_tmet`, import)
- Modify: `scripts/ingestions/tests/test_pipeline_e2e_mef3.py` (same)

- [ ] **Step 1a: Put `tests/` on sys.path so `from _helpers...` works from subfolders**

In `scripts/ingestions/tests/conftest.py`, immediately after the existing `if str(_INGEST_DIR) not in sys.path:` block, append:

```python
# Also make tests/ itself importable so subfolder tests can do
# `from _helpers.builders import ...` without having to spell
# `tests._helpers.builders` everywhere.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
```

- [ ] **Step 1: Create the package init**

Create `scripts/ingestions/tests/_helpers/__init__.py`:

```python
"""Shared test helpers (synthetic fixture builders, factories)."""
```

- [ ] **Step 2: Create `_helpers/builders.py`**

Create `scripts/ingestions/tests/_helpers/builders.py`:

```python
"""Synthetic-fixture builders shared by parser, digest, and pipeline tests.

Each builder constructs a minimal but valid binary fixture on disk so a
test can exercise the parser/digest path without committing the file
into ``eegdash-testing-data``. Anything that can be regenerated cheaply
lives here; anything that needs real signal data lives in the corpus.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np


def build_synthetic_set_v5(
    path: Path,
    *,
    srate: float = 250.0,
    nbchan: int = 32,
    pnts: int = 5000,
    ch_names: list[str] | None = None,
) -> Path:
    """Construct a minimal EEGLAB .set file in MAT v5 format.

    EEGLAB's struct shape (from the .set parser's reading code):
        EEG.srate         — sampling rate in Hz
        EEG.nbchan        — channel count
        EEG.pnts          — number of samples
        EEG.chanlocs      — struct array with .labels (channel names)
    """
    import scipy.io as scipy_io

    if ch_names is None:
        ch_names = [f"Ch{i + 1}" for i in range(nbchan)]

    chanlocs_dtype = np.dtype([("labels", "O")])
    chanlocs = np.zeros(nbchan, dtype=chanlocs_dtype)
    for i, name in enumerate(ch_names):
        chanlocs[i] = (name,)

    eeg_struct = {
        "srate": np.array([[srate]]),
        "nbchan": np.array([[nbchan]]),
        "pnts": np.array([[pnts]]),
        "chanlocs": chanlocs,
    }
    scipy_io.savemat(str(path), {"EEG": eeg_struct}, do_compression=False)
    return path


def build_mefd_around_real_tmet(
    tmp_path: Path,
    real_tmet: Path,
    *,
    channels: list[str] | None = None,
) -> Path:
    """Construct a .mefd directory using a real .tmet fixture.

    Per the MEF 3.0 directory layout, each channel needs its own
    ``<channel>.timd/<channel>-000000.segd/<channel>-000000.tmet`` path.
    Copies the same real .tmet into each channel's location so every
    channel loads the canonical fixture. Returns the .mefd path.
    """
    if channels is None:
        channels = ["EKG", "LAD1", "LAD2"]

    mefd = tmp_path / "sub-test_ieeg.mefd"
    mefd.mkdir()
    for ch in channels:
        segd = mefd / f"{ch}.timd" / f"{ch}-000000.segd"
        segd.mkdir(parents=True)
        shutil.copy(real_tmet, segd / f"{ch}-000000.tmet")
    return mefd


def build_minimal_mef3_bids_root(
    tmp_path: Path,
    real_tmet: Path,
    *,
    dataset_id: str = "ds_mef3_real",
) -> tuple[Path, Path]:
    """Build a minimal BIDS root with one MEF3 .mefd ingest under sub-01.

    Returns (bids_root, mefd_path). The caller can pass bids_root to
    digest_dataset() and mefd_path to direct parse_mef3_metadata() calls.
    """
    bids_root = tmp_path / dataset_id
    bids_root.mkdir()
    (bids_root / "dataset_description.json").write_text(
        '{"Name": "MEF3 real", "BIDSVersion": "1.8.0", "License": "CC0"}'
    )
    (bids_root / "participants.tsv").write_text("participant_id\nsub-01\n")
    sub_ieeg = bids_root / "sub-01" / "ses-ieeg01" / "ieeg"
    sub_ieeg.mkdir(parents=True)
    mefd = build_mefd_around_real_tmet(sub_ieeg, real_tmet)
    return bids_root, mefd


__all__ = [
    "build_synthetic_set_v5",
    "build_mefd_around_real_tmet",
    "build_minimal_mef3_bids_root",
]
```

- [ ] **Step 3: Update `test_set_happy_path.py` to import the builder**

Find the local `_build_synthetic_set_v5` definition (~ lines 31-64) and delete it. Add at the top of the imports section:

```python
from _helpers.builders import build_synthetic_set_v5
```

Then update every call site `_build_synthetic_set_v5(...)` → `build_synthetic_set_v5(...)`.

- [ ] **Step 4: Update `test_mef3_real_fixture.py` to import the builders**

Find the local `_build_mefd_around_real_tmet` definition and delete it. Replace with at top of imports:

```python
from _helpers.builders import build_mefd_around_real_tmet
```

Update call sites: `_build_mefd_around_real_tmet(tmp_path, channels=...)` → `build_mefd_around_real_tmet(tmp_path, _TMET_FIXTURE, channels=...)`.

- [ ] **Step 5: Update `test_pipeline_e2e_mef3.py` to import the builders**

Replace the local `_build_minimal_mef3_bids_root` definition with:

```python
from _helpers.builders import build_minimal_mef3_bids_root, build_mefd_around_real_tmet
```

Update call sites.

- [ ] **Step 6: Run the affected tests**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest \
    tests/test_set_happy_path.py tests/test_mef3_real_fixture.py \
    tests/test_pipeline_e2e_mef3.py \
    -q --tb=line
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/ingestions/tests/_helpers/ \
        scripts/ingestions/tests/test_set_happy_path.py \
        scripts/ingestions/tests/test_mef3_real_fixture.py \
        scripts/ingestions/tests/test_pipeline_e2e_mef3.py
git commit -m "test: extract synthetic-fixture builders into tests/_helpers/builders.py

Removes three duplicated builder definitions from individual test files
and gives every future test that needs a synthetic .set / .mefd / mini-
BIDS root a single import."
```

---

### Task 1.5: Drop duplicate `sys.path.insert` prologues from every test file

**Files (45 files):** every `tests/test_*.py` that contains the 5-line `_INGEST_DIR = Path(__file__).resolve().parent.parent` prologue. The root `conftest.py` already handles this for the whole tree.

- [ ] **Step 1: Audit all duplicates**

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  grep -l "_INGEST_DIR = Path(__file__).resolve().parent.parent" \
    scripts/ingestions/tests/test_*.py | wc -l
```

Expected: 45.

- [ ] **Step 2: Strip the prologue everywhere it appears**

Run this single sed pipeline (it removes the 4-line block + the trailing blank line). The regex anchors on the exact pattern.

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  for f in $(grep -l "_INGEST_DIR = Path(__file__).resolve().parent.parent" scripts/ingestions/tests/test_*.py); do
    python - "$f" <<'PY'
import sys, re, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text()
# 4-line prologue + optional trailing blank line
pat = re.compile(
    r"_INGEST_DIR = Path\(__file__\)\.resolve\(\)\.parent\.parent\n"
    r"if str\(_INGEST_DIR\) not in sys\.path:\n"
    r"    sys\.path\.insert\(0, str\(_INGEST_DIR\)\)\n"
    r"(?:\n)?"
)
new = pat.sub("", text)
# If the file no longer uses Path, drop the now-unused `from pathlib import Path`
if "Path(" not in new and "Path[" not in new:
    new = re.sub(r"^from pathlib import Path\n", "", new, flags=re.M)
# Drop now-unused `import sys`
if "sys." not in new and "import sys" not in new.replace("import sys\n", ""):
    new = re.sub(r"^import sys\n", "", new, flags=re.M)
p.write_text(new)
PY
  done
```

- [ ] **Step 3: Run ruff to clean up any newly-unused imports the script missed**

```bash
cd scripts/ingestions && ruff check --fix tests/ 2>&1 | tail -5
```

- [ ] **Step 4: Full test sweep**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/ -q -m "not network and not slow" --tb=short 2>&1 | tail -15
```

Expected: same pass count as before this task (no regressions). Anything failing means a removed `import sys` was actually needed (look at the file, add it back).

- [ ] **Step 5: Commit**

```bash
git add -u scripts/ingestions/tests/
git commit -m "test: drop duplicate sys.path bootstrap from 45 test files

The root tests/conftest.py already inserts the ingestion directory into
sys.path for the whole tree (pytest picks the parent conftest up from
any subfolder), so the per-file dance was always redundant."
```

---

## Phase 2 — Subfolder moves (PARALLEL — dispatch one subagent per task)

Each Phase-2 task touches a disjoint set of files. They can run concurrently. Dispatch them as parallel subagents.

### Task 2.1 (parallel): Create `parsers/` subfolder with merged parser tests

**Files:**
- Create: `scripts/ingestions/tests/parsers/__init__.py` (empty)
- Move: `tests/test_format_parser_registry.py` → `tests/parsers/test_format_registry.py`
- Move: `tests/test_vhdr_parser.py` → `tests/parsers/test_vhdr.py`
- Merge 3 → 1: `test_set_parser.py` + `test_set_parser_direct.py` + `test_set_happy_path.py` → `tests/parsers/test_set.py`
- Merge 3 → 1: `test_snirf_parser.py` + `test_snirf_happy_path.py` + `test_snirf_real_fixture.py` → `tests/parsers/test_snirf.py`
- Merge 2 → 1: `test_mef3_parser.py` + `test_mef3_real_fixture.py` → `tests/parsers/test_mef3.py`
- Move: `test_parsers_property.py` → `tests/parsers/test_property.py`
- Move: `test_parsers_direct_extended.py` → `tests/parsers/test_extended.py`

- [ ] **Step 1: Create the subfolder**

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  mkdir -p scripts/ingestions/tests/parsers && \
  touch scripts/ingestions/tests/parsers/__init__.py
```

- [ ] **Step 2: Trivial moves (single source → single destination)**

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_format_parser_registry.py \
         scripts/ingestions/tests/parsers/test_format_registry.py && \
  git mv scripts/ingestions/tests/test_vhdr_parser.py \
         scripts/ingestions/tests/parsers/test_vhdr.py && \
  git mv scripts/ingestions/tests/test_parsers_property.py \
         scripts/ingestions/tests/parsers/test_property.py && \
  git mv scripts/ingestions/tests/test_parsers_direct_extended.py \
         scripts/ingestions/tests/parsers/test_extended.py
```

- [ ] **Step 3: Merge the three `.set` files into `parsers/test_set.py`**

Create `scripts/ingestions/tests/parsers/test_set.py` with the three section headers below. Copy the *test functions only* (after the prologue and the local `_build_synthetic_set_v5` definition that already migrated to `_helpers` in Phase 1.4) verbatim from each source file, then delete the originals.

File scaffold:

```python
"""Tests for the EEGLAB .set parser.

Three angles in one file:
- **Golden** — pinned values against the truncated CC0 fixture
  ``eeg/sub-001_task-AuditoryVisualShift_run-01_eeg.set`` (was test_set_parser.py).
- **Direct** — happy-path through scipy.io / h5py on the same real fixture
  (was test_set_parser_direct.py).
- **Synthetic MAT v5** — in-memory fixtures via _helpers.builders that
  exercise every extraction branch (was test_set_happy_path.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eegdash.testing import data_file

from _set_parser import diagnose_set_issues, parse_set_metadata
from _helpers.builders import build_synthetic_set_v5

EEG_SET = data_file("eeg/sub-001_task-AuditoryVisualShift_run-01_eeg.set")

# ── 1. Golden values on the truncated fixture ──────────────────────────
# (copy every test function from test_set_parser.py here)

# ── 2. Direct extraction on the same fixture ───────────────────────────
# (copy every test function from test_set_parser_direct.py here)

# ── 3. Synthetic MAT v5 — every extraction branch ──────────────────────
# (copy every test function from test_set_happy_path.py here)
```

Then:

```bash
git rm scripts/ingestions/tests/test_set_parser.py \
       scripts/ingestions/tests/test_set_parser_direct.py \
       scripts/ingestions/tests/test_set_happy_path.py
```

- [ ] **Step 4: Merge the three `.snirf` files**

Same pattern, create `scripts/ingestions/tests/parsers/test_snirf.py`:

```python
"""Tests for the SNIRF (HDF5-based) parser.

Three angles:
- **Parser unit** — direct invariants on the parser API (was test_snirf_parser.py).
- **Happy path on synthetic h5py** — covers every extraction branch
  (was test_snirf_happy_path.py).
- **Real fixture** — golden values on ``fnirs/openneuro_real.snirf``
  (was test_snirf_real_fixture.py).
"""
# (function bodies copied verbatim, three section headers)
```

```bash
git rm scripts/ingestions/tests/test_snirf_parser.py \
       scripts/ingestions/tests/test_snirf_happy_path.py \
       scripts/ingestions/tests/test_snirf_real_fixture.py
```

- [ ] **Step 5: Merge the two `.mef3` files**

Create `scripts/ingestions/tests/parsers/test_mef3.py`:

```python
"""Tests for the MEF3 (.mefd / .tmet) parser.

Two angles:
- **Parser unit** — invariants + edge cases on the parser API
  (was test_mef3_parser.py).
- **Real fixture** — golden values on ``ieeg/EKG-000000.tmet``
  (was test_mef3_real_fixture.py).
"""
# (function bodies copied verbatim, two section headers)
```

```bash
git rm scripts/ingestions/tests/test_mef3_parser.py \
       scripts/ingestions/tests/test_mef3_real_fixture.py
```

- [ ] **Step 6: Run the parsers subfolder**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/parsers/ -q --tb=line
```

Expected: every test from the original 8 files passes — same count.

- [ ] **Step 7: Commit**

```bash
git add scripts/ingestions/tests/parsers/
git commit -m "test(parsers): consolidate format-parser tests into parsers/ subfolder

8 source files → 7 destination files:
- 3 trivial moves (vhdr / format_registry / property / extended)
- 3 merges (set: 3→1, snirf: 3→1, mef3: 2→1)
Each merge keeps every assertion; the three angles (golden / direct /
synthetic) become section headers in one file."
```

---

### Task 2.2 (parallel): Create `unit/` subfolder + merge unit tests

**Files:**
- Create: `scripts/ingestions/tests/unit/__init__.py`
- Move: 11 files unchanged
- Merge: 3 files

- [ ] **Step 1: Create folder**

```bash
mkdir -p scripts/ingestions/tests/unit && \
  touch scripts/ingestions/tests/unit/__init__.py
```

- [ ] **Step 2: Trivial moves**

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_fingerprint.py        scripts/ingestions/tests/unit/test_fingerprint.py && \
  git mv scripts/ingestions/tests/test_parser_utils.py       scripts/ingestions/tests/unit/test_parser_utils.py && \
  git mv scripts/ingestions/tests/test_parser_utils_network.py scripts/ingestions/tests/unit/test_parser_utils_network.py && \
  git mv scripts/ingestions/tests/test_serialize_helpers.py  scripts/ingestions/tests/unit/test_serialize.py && \
  git mv scripts/ingestions/tests/test_bids_helpers.py       scripts/ingestions/tests/unit/test_bids_paths.py && \
  git mv scripts/ingestions/tests/test_file_utils_helpers.py scripts/ingestions/tests/unit/test_file_utils.py && \
  git mv scripts/ingestions/tests/test_metadata_cascade.py   scripts/ingestions/tests/unit/test_metadata_cascade.py && \
  git mv scripts/ingestions/tests/test_metadata_provenance.py scripts/ingestions/tests/unit/test_metadata_provenance.py && \
  git mv scripts/ingestions/tests/test_path_traversal.py     scripts/ingestions/tests/unit/test_path_traversal.py && \
  git mv scripts/ingestions/tests/test_rate_limited.py       scripts/ingestions/tests/unit/test_rate_limited.py && \
  git mv scripts/ingestions/tests/test_find_leaked_creds.py  scripts/ingestions/tests/unit/test_find_leaked_creds.py
```

- [ ] **Step 3: Merge 2 → 1: `test_http.py` + `test_http_variants.py` → `unit/test_http.py`**

Create `scripts/ingestions/tests/unit/test_http.py` whose top is:

```python
"""Tests for the shared HTTP client (``_http``).

Two angles:
- **Core API** — request_json, retry classes, header negotiation
  (was test_http.py).
- **Variants** — make_retry_session backwards-compat, status-list
  membership (was test_http_variants.py).
"""
```

Then concatenate the function bodies from both source files, then:

```bash
git rm scripts/ingestions/tests/test_http.py scripts/ingestions/tests/test_http_variants.py
```

- [ ] **Step 4: Merge 2 → 1: `test_validate_functions.py` + `test_validate_helpers.py` → `unit/test_validate.py`**

Same pattern. Two section headers: "Functions" and "Helpers".

```bash
git rm scripts/ingestions/tests/test_validate_functions.py \
       scripts/ingestions/tests/test_validate_helpers.py
```

- [ ] **Step 5: Merge 3 → 1: `test_montage_helpers.py` + `test_montage_cache.py` + `test_montage_annex_key_shortcut.py` → `unit/test_montage.py`**

Three section headers: "Pure helpers", "Cache layer", "git-annex key shortcut".

```bash
git rm scripts/ingestions/tests/test_montage_helpers.py \
       scripts/ingestions/tests/test_montage_cache.py \
       scripts/ingestions/tests/test_montage_annex_key_shortcut.py
```

- [ ] **Step 6: Merge 3 → 1: `test_clone_config.py` + `test_inject_config.py` + `test_stage_configs.py` → `unit/test_stage_configs.py`**

Three section headers: "Clone config", "Inject config", "Cross-stage invariants".

```bash
git rm scripts/ingestions/tests/test_clone_config.py \
       scripts/ingestions/tests/test_inject_config.py \
       scripts/ingestions/tests/test_stage_configs.py
```

- [ ] **Step 7: Run the unit subfolder**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/unit/ -q --tb=line
```

Expected: every test from the 16 original files passes.

- [ ] **Step 8: Commit**

```bash
git add scripts/ingestions/tests/unit/
git commit -m "test(unit): regroup unit tests under unit/ subfolder

16 source files → 12 destination files:
- 11 trivial moves
- 4 merges (http: 2→1, validate: 2→1, montage: 3→1, stage_configs: 3→1)
Each merge preserves every assertion; multiple angles on the same source
module become section headers in one file."
```

---

### Task 2.3 (parallel): Create `digest/` subfolder

**Files:**
- Create: `scripts/ingestions/tests/digest/__init__.py`
- Move: 9 files into `digest/`
- Merge: 2 source-listing files into 1

- [ ] **Step 1: Create folder + simple moves**

```bash
mkdir -p scripts/ingestions/tests/digest && \
  touch scripts/ingestions/tests/digest/__init__.py && \
  cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_digest_extractions.py        scripts/ingestions/tests/digest/test_extractions.py && \
  git mv scripts/ingestions/tests/test_digest_extraction_helpers.py scripts/ingestions/tests/digest/test_extraction_helpers.py && \
  git mv scripts/ingestions/tests/test_digest_helpers.py            scripts/ingestions/tests/digest/test_helpers.py && \
  git mv scripts/ingestions/tests/test_digest_telemetry.py          scripts/ingestions/tests/digest/test_telemetry.py && \
  git mv scripts/ingestions/tests/test_digest_snapshot.py           scripts/ingestions/tests/digest/test_snapshot.py && \
  git mv scripts/ingestions/tests/test_bids_sidecar_enrichment.py   scripts/ingestions/tests/digest/test_bids_sidecar.py && \
  git mv scripts/ingestions/tests/test_record_enumerator.py         scripts/ingestions/tests/digest/test_record_enumerator.py && \
  git mv scripts/ingestions/tests/test_source_adapter.py            scripts/ingestions/tests/digest/test_source_adapter.py
```

- [ ] **Step 2: Merge `test_source_listing.py` + `test_source_listing_extended.py` → `digest/test_source_listing.py`**

Create the merged file with two section headers ("Core listing" / "Extended adapters") then:

```bash
git rm scripts/ingestions/tests/test_source_listing.py \
       scripts/ingestions/tests/test_source_listing_extended.py
```

- [ ] **Step 3: Run digest subfolder**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/digest/ -q --tb=line
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/ingestions/tests/digest/
git commit -m "test(digest): regroup stage-3 tests under digest/ subfolder"
```

---

### Task 2.4 (parallel): Create `github/` subfolder

**Files:**
- Create: `scripts/ingestions/tests/github/__init__.py`
- Move: 3 files

- [ ] **Step 1**

```bash
mkdir -p scripts/ingestions/tests/github && \
  touch scripts/ingestions/tests/github/__init__.py && \
  cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_github_helpers.py         scripts/ingestions/tests/github/test_helpers.py && \
  git mv scripts/ingestions/tests/test_github_pygithub_fastpath.py scripts/ingestions/tests/github/test_pygithub_fastpath.py && \
  git mv scripts/ingestions/tests/test_github_rest_fallback.py   scripts/ingestions/tests/github/test_rest_fallback.py
```

- [ ] **Step 2: Run + commit**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -m pytest tests/github/ -q --tb=line && \
  git commit -m "test(github): regroup GitHub adapter tests under github/ subfolder"
```

---

### Task 2.5 (parallel): Create `inject/` subfolder

**Files:**
- Create: `scripts/ingestions/tests/inject/__init__.py`
- Move: 4 files

- [ ] **Step 1**

```bash
mkdir -p scripts/ingestions/tests/inject && \
  touch scripts/ingestions/tests/inject/__init__.py && \
  cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_inject_api_calls.py            scripts/ingestions/tests/inject/test_api_calls.py && \
  git mv scripts/ingestions/tests/test_inject_helpers.py              scripts/ingestions/tests/inject/test_helpers.py && \
  git mv scripts/ingestions/tests/test_inject_integration_live.py     scripts/ingestions/tests/inject/test_integration_live.py && \
  git mv scripts/ingestions/tests/test_inject_integration_stress.py   scripts/ingestions/tests/inject/test_integration_stress.py
```

- [ ] **Step 2: Run + commit**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -m pytest tests/inject/ -q --tb=line && \
  git commit -m "test(inject): regroup stage-5 inject tests under inject/ subfolder"
```

---

### Task 2.6 (parallel): Create `pipeline/` subfolder

**Files:**
- Create: `scripts/ingestions/tests/pipeline/__init__.py`
- Move: 4 files

- [ ] **Step 1**

```bash
mkdir -p scripts/ingestions/tests/pipeline && \
  touch scripts/ingestions/tests/pipeline/__init__.py && \
  cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_pipeline_e2e.py          scripts/ingestions/tests/pipeline/test_e2e.py && \
  git mv scripts/ingestions/tests/test_pipeline_e2e_mef3.py     scripts/ingestions/tests/pipeline/test_e2e_mef3.py && \
  git mv scripts/ingestions/tests/test_pipeline_invariants.py   scripts/ingestions/tests/pipeline/test_invariants.py && \
  git mv scripts/ingestions/tests/test_schema_preflight.py      scripts/ingestions/tests/pipeline/test_schema_preflight.py
```

- [ ] **Step 2: Move clone-error-handling here too (it's a pipeline-level test, not unit)**

```bash
cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_clone_error_handling.py scripts/ingestions/tests/pipeline/test_clone_error_handling.py
```

- [ ] **Step 3: Run + commit**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -m pytest tests/pipeline/ -q --tb=line && \
  git commit -m "test(pipeline): regroup end-to-end + invariant tests under pipeline/ subfolder"
```

---

### Task 2.7 (parallel): Create `perf/` subfolder

**Files:**
- Create: `scripts/ingestions/tests/perf/__init__.py`
- Move: 2 files

- [ ] **Step 1**

```bash
mkdir -p scripts/ingestions/tests/perf && \
  touch scripts/ingestions/tests/perf/__init__.py && \
  cd /Users/bruaristimunha/Projects/EEGDash && \
  git mv scripts/ingestions/tests/test_perf.py               scripts/ingestions/tests/perf/test_perf.py && \
  git mv scripts/ingestions/tests/test_manifest_walk_perf.py scripts/ingestions/tests/perf/test_manifest_walk.py
```

- [ ] **Step 2: Update the bench CI workflow to point at the new path**

In `.github/workflows/ingestions-bench.yml`, replace:

```yaml
          pytest tests/test_perf.py \
            -m "slow or not slow" \
```

with:

```yaml
          pytest tests/perf/ \
            -m "slow or not slow" \
```

- [ ] **Step 3: Run + commit**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache python -m pytest tests/perf/ -q -m "not slow" --tb=line && \
  cd /Users/bruaristimunha/Projects/EEGDash && \
  git add scripts/ingestions/tests/perf/ .github/workflows/ingestions-bench.yml && \
  git commit -m "test(perf): move perf gates under perf/ subfolder + update bench workflow"
```

---

## Phase 3 — Cleanup + verification (sequential)

### Task 3.1: Update `pyproject.toml` per-file-ignores for the new layout

**Files:**
- Modify: `scripts/ingestions/pyproject.toml` (the `[tool.ruff.lint.per-file-ignores]` block)

The existing entries are:
```toml
"tests/*.py" = ["D", "N802", "N806", "RUF002", "RUF003", "BLE001"]
"tests/acceptance/*.py" = ["D", "N802", "N806", "RUF002", "RUF003", "BLE001"]
```

- [ ] **Step 1: Replace the two entries with a recursive glob**

In `scripts/ingestions/pyproject.toml`, replace those two lines with:

```toml
"tests/**/*.py" = ["D", "N802", "N806", "RUF002", "RUF003", "BLE001"]
```

- [ ] **Step 2: Run ruff over everything**

```bash
cd scripts/ingestions && ruff check tests/ 2>&1 | tail -5
```

Expected: `All checks passed!`

- [ ] **Step 3: Commit**

```bash
git add scripts/ingestions/pyproject.toml
git commit -m "lint: collapse tests/*.py + tests/acceptance/*.py per-file-ignores to tests/**/*.py"
```

---

### Task 3.2: Final full-suite verification

- [ ] **Step 1: Full pytest run (offline-skippable tests included)**

```bash
cd scripts/ingestions && \
  EEGDASH_TESTING_DATA_DIR=/tmp/eegdash-test-cache \
  python -m pytest tests/ -q -m "not network and not slow" --tb=short 2>&1 | tail -10
```

Expected: same pass count as the baseline captured at the start of Phase 1 (no regressions).

- [ ] **Step 2: Push the whole sequence**

```bash
git push origin record-enumerator-merge
```

- [ ] **Step 3: Arm a CI monitor**

(Performed by the orchestrator, not the executor.) Confirm the four ingestion checks (Validate fixture records / Lint+Test / Pipeline E2E / Benchmark+Memory) flip green on the new HEAD.

---

## Acceptance criteria — apply at the end of Phase 3

- `tests/` contains **0** files directly under it whose names match `test_*.py` except `tests/test_smoke.py`.
- `tests/_helpers/` exposes `build_synthetic_set_v5`, `build_mefd_around_real_tmet`, `build_minimal_mef3_bids_root`.
- `tests/fixtures/` contains only `records/` (and the now-empty `digest_snapshots/` is deleted).
- `eegdash/testing.py` is pinned to `v0.2.0` with the recomputed SHA-256.
- The on-PR pytest unit count is **equal to** the baseline pre-reorg count (no test was lost in the merges).
- `python -m pytest tests/ -m "not network and not slow"` exits 0 locally.
- `grep -r "Path(__file__).resolve().parent.parent" scripts/ingestions/tests/ --include="*.py" | wc -l` returns **1** (only the root conftest).

---

## Parallel execution map for the subagent driver

```
Phase 0 → sequential
   ↓
Phase 1.1 → Phase 1.2 → Phase 1.3 → Phase 1.4 → Phase 1.5    (sequential — foundation)
   ↓
Phase 2.1  Phase 2.2  Phase 2.3  Phase 2.4  Phase 2.5  Phase 2.6  Phase 2.7   ← dispatch in parallel
   ↓
Phase 3.1 → Phase 3.2    (sequential — global cleanup)
```

7 parallel subagents in Phase 2 cut wall-clock time roughly in half compared to running them sequentially.
