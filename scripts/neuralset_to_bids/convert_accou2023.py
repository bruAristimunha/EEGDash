#!/usr/bin/env python3
from __future__ import annotations

"""Prepare the Accou et al. 2023 SparrKULee dataset for re-hosting on NEMAR.

SparrKULee is already published in BIDS-EEG format on the KU Leuven Research
Data Repository (DOI: 10.48804/K3VSND), so this script is NOT a full
converter — it only applies the minimal fixes needed so the dataset passes
the modern BIDS validator and to **exclude the 5 subjects whose files are
access-restricted**.

Restricted subjects (data not publicly downloadable, returns HTTP 403 from
the KU Leuven Dataverse):

  - sub-019, sub-020, sub-021, sub-022, sub-026

Researchers who need these subjects must request access directly from the
authors (sparrkulee@kuleuven.be) and download them from the official KU
Leuven Dataverse page at https://doi.org/10.48804/K3VSND.

Fixes applied:
  1. Remove directories for restricted subjects and mark them in
     `participants.tsv` with an `exclusion_note` column.
  2. Add a prominent warning to `README` and `dataset_description.json`
     describing the exclusion.
  3. Fix `participants.tsv` age column: the age is stored as a string
     range (e.g. "21 to 23"); we move it to a new `age_range` column and
     set `age` to n/a. Also update `participants.json` accordingly.
  4. Move per-session `remarks/` text files out of the BIDS subject
     hierarchy and into `/code/remarks/` (the BIDS validator does not
     recognize arbitrary `remarks/` folders inside `sub-XX/ses-YY/`).
  5. Keep the original `*.bdf.gz` EEG files — they are legal in BIDS when
     whitelisted via `.bidsignore` (the upstream dataset already does
     this), and decompressing would roughly double the on-disk footprint.

Usage:
    python convert_accou2023.py --input /tmp/accou2023 --dry-run
    python convert_accou2023.py --input /tmp/accou2023
"""

import argparse
import json
import logging
import shutil
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Subjects whose files are access-restricted on the KU Leuven Dataverse.
# Re-downloading requires applying to sparrkulee@kuleuven.be.
RESTRICTED_SUBJECTS = ["sub-019", "sub-020", "sub-021", "sub-022", "sub-026"]

EXCLUSION_REASON = (
    "access-restricted on KU Leuven Dataverse (data returns HTTP 403 "
    "without explicit permission)"
)

RESTRICTED_WARNING = (
    "IMPORTANT — 5 of the 85 original subjects (sub-019, sub-020, "
    "sub-021, sub-022, sub-026) are EXCLUDED from this NEMAR re-host "
    "because their raw EEG files are access-restricted on the KU Leuven "
    "Dataverse (HTTP 403 on download without a data-use agreement). "
    "Researchers who need these subjects should email "
    "sparrkulee@kuleuven.be to request access and download the data "
    "directly from https://rdr.kuleuven.be/dataset.xhtml?persistentId=doi:10.48804/K3VSND "
    "(DOI 10.48804/K3VSND). The re-host therefore contains 80 of the "
    "original 85 subjects, covering all 11 session types (shortstories01, "
    "varyingStories01..10)."
)

COHORT_NOTE = (
    "Cohort demographics (from Accou et al., Data 2024, 9, 94, Section "
    "2.1): 85 original participants, 74 female / 11 male, aged 21.4 ± 1.9 "
    "years (mean ± SD), inclusion window 18-30 years, all normal-hearing "
    "(≤30 dB HL, 125-8000 Hz), native Dutch/Flemish speakers. Per-subject "
    "numeric ages are not published by the SparrKULee authors for privacy "
    "reasons; `participants.tsv` only ships 3-year binned ages in the "
    "`age_range` column (see `participants.json` for details)."
)

HOW_TO_ACKNOWLEDGE = (
    "Please cite the original SparrKULee data descriptor when using this "
    "dataset: Accou, B., Bollens, L., Gillis, M., Verheijen, W., "
    "Van hamme, H., & Francart, T. (2024). SparrKULee: A Speech-Evoked "
    "Auditory Response Repository from KU Leuven, Containing the EEG of "
    "85 Participants. Data, 9(8), 94. https://doi.org/10.3390/data9080094"
)

PAPER_URL = "https://doi.org/10.3390/data9080094"


def remove_restricted_subjects(bids_root: Path, dry_run: bool = False) -> list[str]:
    """Delete the 5 restricted subject directories. Returns the list of
    removed subjects.
    """
    removed = []
    for sub in RESTRICTED_SUBJECTS:
        sub_dir = bids_root / sub
        if sub_dir.exists():
            if dry_run:
                logger.info("[DRY] Would remove %s", sub_dir)
            else:
                shutil.rmtree(sub_dir)
                logger.info("Removed %s", sub_dir)
            removed.append(sub)
        else:
            logger.info("%s already absent", sub)
    return removed


def fix_participants_tsv(bids_root: Path, dry_run: bool = False) -> None:
    """Mark restricted subjects in participants.tsv and fix the age column.

    The published participants.tsv uses string ranges like "21 to 23" in the
    `age` column, which the BIDS validator rejects (age must be numeric).
    We rename that column to `age_range` and leave `age` set to "n/a" so the
    validator accepts it.
    """
    tsv_path = bids_root / "participants.tsv"
    if not tsv_path.exists():
        logger.warning("No participants.tsv at %s", tsv_path)
        return

    df = pd.read_csv(tsv_path, sep="\t", dtype=str)

    # Move age to age_range
    if "age" in df.columns and "age_range" not in df.columns:
        df["age_range"] = df["age"]
        df["age"] = "n/a"

    # Add exclusion_note column
    if "exclusion_note" not in df.columns:
        df["exclusion_note"] = "n/a"
    df.loc[df["participant_id"].isin(RESTRICTED_SUBJECTS), "exclusion_note"] = (
        EXCLUSION_REASON
    )

    # Reorder so exclusion_note is last for readability
    cols = [c for c in df.columns if c != "exclusion_note"] + ["exclusion_note"]
    df = df[cols]

    if dry_run:
        logger.info("[DRY] Would rewrite %s (%d rows)", tsv_path, len(df))
        logger.info(
            "Sample restricted rows:\n%s",
            df[df["participant_id"].isin(RESTRICTED_SUBJECTS)].to_string(),
        )
        return

    df.to_csv(tsv_path, sep="\t", index=False, na_rep="n/a")
    logger.info("Rewrote %s", tsv_path)


def fix_participants_json(bids_root: Path, dry_run: bool = False) -> None:
    """Add age_range + exclusion_note column descriptions to participants.json."""
    path = bids_root / "participants.json"
    if not path.exists():
        logger.warning("No participants.json at %s", path)
        return

    with open(path) as f:
        desc = json.load(f)

    # Fix age: the upstream SparrKULee release ships a stale description
    # ("Age of the participant at the time of the scan." / Units: "years"),
    # which no longer matches the actual TSV contents. We moved every numeric
    # value into `age_range`, so the `age` column is now always "n/a".
    # Rewrite the entry unconditionally to match reality — and drop Units,
    # since there is no numeric value to carry units for.
    desc["age"] = {
        "Description": (
            "Always n/a in this NEMAR re-host. The upstream SparrKULee "
            "release stored age as a string range (e.g. '21 to 23') in "
            "this column, which the BIDS validator rejects (age must be "
            "numeric). The original string values have been moved to "
            "`age_range` and this column is set to n/a for validator "
            "compliance. Per-subject numeric ages are not published by "
            "the SparrKULee authors for privacy reasons; only the "
            "cohort-level aggregate is reported in the paper: 21.4 ± "
            "1.9 years (mean ± SD), inclusion window 18-30 years "
            "(Accou et al., Data 2024, 9, 94, Section 2.1)."
        ),
    }
    desc["age_range"] = {
        "Description": (
            "Approximate age range (string, e.g. '18 to 20'). Original "
            "SparrKULee `age` column values were 3-year bins; this column "
            "preserves them verbatim."
        )
    }
    desc["exclusion_note"] = {
        "Description": (
            "Reason a subject is excluded from the NEMAR re-host. 'n/a' "
            "means the subject is included. Subjects with "
            "'access-restricted on KU Leuven Dataverse ...' are the 5 "
            "subjects whose raw EEG files require a data-use agreement."
        )
    }

    if dry_run:
        logger.info("[DRY] Would rewrite %s", path)
        return

    with open(path, "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")
    logger.info("Rewrote %s", path)


def fix_dataset_description(bids_root: Path, dry_run: bool = False) -> None:
    """Add the restricted-subjects warning and NEMAR GeneratedBy block."""
    path = bids_root / "dataset_description.json"
    if not path.exists():
        logger.warning("No dataset_description.json at %s", path)
        return

    with open(path) as f:
        desc = json.load(f)

    # Add a prominent warning + cohort demographics at the top level.
    # Idempotent: the marker substring "access-restricted" is only present if
    # a previous run already merged our block, so we don't duplicate on re-run.
    notes = desc.get("Notes") or ""
    if "access-restricted" not in notes:
        augmented = RESTRICTED_WARNING + "\n\n" + COHORT_NOTE
        desc["Notes"] = augmented if not notes else (notes + "\n\n" + augmented)

    # `HowToAcknowledge` is a BIDS-recommended top-level key. Pointing it at
    # the original SparrKULee data descriptor keeps citation credit with the
    # upstream authors even after NEMAR re-hosts the dataset.
    if not desc.get("HowToAcknowledge"):
        desc["HowToAcknowledge"] = HOW_TO_ACKNOWLEDGE

    # Surface the peer-reviewed data descriptor in ReferencesAndLinks. The
    # upstream release only links the GitHub code repo, which is not the
    # canonical citation.
    existing_refs = desc.get("ReferencesAndLinks") or []
    if PAPER_URL not in existing_refs:
        existing_refs.append(PAPER_URL)
    desc["ReferencesAndLinks"] = existing_refs

    # Track that we modified the dataset for NEMAR
    existing_gb = desc.get("GeneratedBy") or []
    if not any("EEGDash" in (gb.get("Name") or "") for gb in existing_gb):
        existing_gb.append(
            {
                "Name": "convert_accou2023.py (EEGDash)",
                "Description": (
                    "Prepared the original SparrKULee BIDS dataset for "
                    "NEMAR re-hosting: excluded 5 access-restricted "
                    "subjects (sub-019..022, sub-026), moved the "
                    "string-range `age` column into `age_range` and set "
                    "`age` to n/a, moved per-session `remarks/` text "
                    "files into `/code/remarks/`, moved orphan "
                    "top-level EEG sidecar into `/code/` (the raw EEG "
                    "ships as `.bdf.gz` which the validator does not "
                    "recognize as a BIDS data suffix), filled in "
                    "recommended task-level metadata "
                    "(TaskName/Description/Instructions/Institution*/"
                    "StimulusPresentation) on the top-level `_beh.json` "
                    "and `_events.json` sidecars, and added a prominent "
                    "exclusion warning plus cohort demographics to "
                    "README and dataset_description.json."
                ),
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        )
    desc["GeneratedBy"] = existing_gb

    if "HEDVersion" not in desc:
        desc["HEDVersion"] = "8.2.0"

    # Bump BIDSVersion to current (was 1.8.0)
    if desc.get("BIDSVersion", "0").startswith("1.8"):
        desc["BIDSVersion"] = "1.9.0"

    # Point to the upstream KU Leuven Dataverse record so provenance is
    # explicit and the validator's JSON_KEY_RECOMMENDED warning for
    # SourceDatasets is resolved. DatasetDOI stays untouched — NEMAR will
    # overwrite it with its own DOI at publish time.
    existing_sources = desc.get("SourceDatasets") or []
    if not any(
        (s.get("DOI") or "").endswith("10.48804/K3VSND") for s in existing_sources
    ):
        existing_sources.append(
            {
                "URL": (
                    "https://rdr.kuleuven.be/dataset.xhtml"
                    "?persistentId=doi:10.48804/K3VSND"
                ),
                "DOI": "doi:10.48804/K3VSND",
            }
        )
    desc["SourceDatasets"] = existing_sources

    if dry_run:
        logger.info("[DRY] Would rewrite %s", path)
        return

    with open(path, "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")
    logger.info("Rewrote %s", path)


def fix_readme(bids_root: Path, dry_run: bool = False) -> None:
    """Prepend the restricted-subjects warning to the README."""
    path = bids_root / "README.md"
    if not path.exists():
        path = bids_root / "README"
    if not path.exists():
        logger.warning("No README at %s", bids_root)
        return

    content = path.read_text()
    if "access-restricted" in content:
        logger.info("README already contains the exclusion warning")
        return

    warning_block = (
        "=============================================================\n"
        "IMPORTANT — RESTRICTED SUBJECTS EXCLUDED FROM NEMAR RE-HOST\n"
        "=============================================================\n\n"
        + RESTRICTED_WARNING
        + "\n\n"
        "Excluded subjects: " + ", ".join(RESTRICTED_SUBJECTS) + "\n\n"
        "Cohort demographics\n"
        "-------------------\n\n" + COHORT_NOTE + "\n\n"
        "How to cite\n"
        "-----------\n\n" + HOW_TO_ACKNOWLEDGE + "\n\n"
        "Where extra metadata lives (after NEMAR preparation)\n"
        "----------------------------------------------------\n\n"
        "  * `/code/task-listeningActive_eeg.json` — full recording-level "
        "EEG metadata (SamplingFrequency, Manufacturer, EEGChannelCount, "
        "EEGReference, PowerLineFrequency, ...). Relocated from the "
        "dataset root because the validator does not match the orphan "
        "top-level sidecar against the `.bdf.gz` data files.\n"
        "  * `/code/remarks/` — per-session free-form recording notes "
        "(`.txt` and `.docx`) originally placed under "
        "`sub-XX/ses-YY/remarks/`. Relocated so the validator does not "
        "see an arbitrary `remarks/` folder inside BIDS session "
        "directories.\n"
        "  * `/code/convert_accou2023.py` — the exact script that was "
        "run to produce this NEMAR re-host.\n\n"
        "-------------------------------------------------------------\n\n"
    )

    new_content = warning_block + content

    if dry_run:
        logger.info("[DRY] Would prepend warning to %s", path)
        return

    path.write_text(new_content)
    logger.info("Prepended warning to %s", path)


def clean_duplicate_events_tsv(bids_root: Path, dry_run: bool = False) -> int:
    """Remove `*_events-1.tsv` / `*_events-2.tsv` duplicates.

    The upstream release contains a handful of files with names like
    `sub-024_..._run-09_events-1.tsv` alongside the canonical
    `sub-024_..._run-09_events.tsv`. The dash-number suffix is not a BIDS
    entity, so the validator rejects them as malformed filenames. They are
    exact duplicates of the canonical file, so we safely remove them.
    """
    import re

    removed = 0
    pattern = re.compile(r"_events-\d+\.tsv$")
    for fp in sorted(bids_root.glob("sub-*/ses-*/eeg/*_events-*.tsv")):
        if not pattern.search(fp.name):
            continue
        if dry_run:
            logger.info("[DRY] Would remove %s", fp)
        else:
            fp.unlink()
            logger.info("Removed duplicate events file: %s", fp.name)
        removed += 1
    return removed


# Non-BIDS download artifacts that were left behind in the dataset root by
# the aria2 fetch script used to pull the data from the KU Leuven Dataverse.
# They are not part of the published dataset and should never ship with the
# NEMAR re-host.
_DOWNLOAD_ARTIFACTS = ("aria2.txt", "missing_aria2.txt")


def clean_download_artifacts(bids_root: Path, dry_run: bool = False) -> int:
    """Delete aria2 download lists from the dataset root.

    Keeping them would leak the private mirror layout and inflate the NEMAR
    upload with files that are not part of the published dataset.
    """
    removed = 0
    for name in _DOWNLOAD_ARTIFACTS:
        fp = bids_root / name
        if not fp.exists():
            continue
        if dry_run:
            logger.info("[DRY] Would remove download artifact %s", fp)
        else:
            fp.unlink()
            logger.info("Removed download artifact %s", fp.name)
        removed += 1
    return removed


def fix_task_listening_eeg_sidecar(bids_root: Path, dry_run: bool = False) -> None:
    """Rename the top-level `task-listeningActive_eeg.json` so the BIDS
    validator does not flag it as a sidecar without a matching data file.

    Because the raw EEG files are stored as `*.bdf.gz` (whitelisted via
    `.bidsignore`), the validator does not see any `*.bdf` files matching
    the top-level task sidecar and reports SIDECAR_WITHOUT_DATAFILE. The
    JSON itself contains useful per-task metadata (TaskName, TaskDescription,
    Instructions, etc.), so we rename it to `task-listeningActive_eeg.json.bak`
    and copy its contents into `/code/` for provenance.
    """
    src = bids_root / "task-listeningActive_eeg.json"
    if not src.exists():
        return
    code_dir = bids_root / "code"
    dest_copy = code_dir / "task-listeningActive_eeg.json"
    if dry_run:
        logger.info(
            "[DRY] Would copy %s -> %s and remove the original",
            src,
            dest_copy,
        )
        return
    code_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_copy)
    src.unlink()
    logger.info(
        "Moved task-listeningActive_eeg.json into code/ "
        "(was an orphan top-level sidecar next to .bdf.gz files)"
    )


# Institution metadata was in the upstream top-level `task-listeningActive_eeg.json`
# which had to be moved to `/code/` to silence SIDECAR_WITHOUT_DATAFILE (because
# the raw EEG files are stored as `.bdf.gz`, which the validator does not
# recognize as a BIDS data suffix). We preserve the same values here so that
# inheritance still reaches the behavioural and events TSVs.
_INSTITUTION_NAME = "ExpORL, KULeuven"
_INSTITUTION_ADDRESS = "Herestraat 49 bus 721, B-3000 Leuven, Belgium"
_INSTITUTIONAL_DEPARTMENT = (
    "ExpORL (Experimental Oto-rhino-laryngology), Department of Neurosciences"
)

# Stimulus-presentation metadata extracted from the `.apr` result files
# shipped with every recording (e.g. `<apex_version>4.0.1</apex_version>`).
# APEX is the KU Leuven ExpORL auditory experiment platform.
_STIMULUS_PRESENTATION = {
    "OperatingSystem": "Microsoft Windows",
    "SoftwareName": "APEX",
    "SoftwareVersion": "4.0.1",
    "Code": "https://exporl.med.kuleuven.be/apex/",
}


def fix_task_sidecars(bids_root: Path, dry_run: bool = False) -> None:
    """Fill in BIDS-recommended keys on top-level task sidecars.

    The upstream SparrKULee release ships bare-bones top-level sidecars
    that only describe individual TSV columns. The BIDS validator then
    warns on every child TSV (hundreds of them) that the sidecar is
    missing recommended task-level keys such as `TaskName`,
    `TaskDescription`, `Instructions`, `Institution*`, and
    `StimulusPresentation`.

    Populating these once on the top-level sidecars resolves the
    SIDECAR_KEY_RECOMMENDED warnings for every inheriting TSV at once.

    Note: `CogAtlasID` and `CogPOID` are intentionally left unset —
    there is no legitimate Cognitive Atlas / Cognitive Paradigm Ontology
    identifier for a pure-tone audiogram or a continuous-speech-listening
    paradigm, and fabricating one would be worse than the residual
    warning.
    """
    fixes: list[tuple[Path, dict]] = [
        (
            bids_root / "task-audiogram_beh.json",
            {
                "TaskName": "audiogram",
                "TaskDescription": (
                    "Pure-tone audiometry screening. At each tone frequency "
                    "the participant's hearing threshold is determined for "
                    "both ears using air and (where applicable) bone "
                    "conduction. Used to verify normal-hearing inclusion "
                    "criteria and to characterise any mild hearing loss."
                ),
                "Instructions": (
                    "Press the response button as soon as you hear a tone, "
                    "no matter how faint."
                ),
                "InstitutionName": _INSTITUTION_NAME,
                "InstitutionAddress": _INSTITUTION_ADDRESS,
                "InstitutionalDepartmentName": _INSTITUTIONAL_DEPARTMENT,
            },
        ),
        (
            bids_root / "task-listeningActive_events.json",
            {
                "TaskName": "listeningActive",
                "TaskDescription": (
                    "Participants listened to continuous natural speech "
                    "(stories, podcasts, audiobooks), optionally presented "
                    "in background noise and/or alongside a silent video, "
                    "and were asked a comprehension question after each "
                    "stimulus trial."
                ),
                "Instructions": (
                    "Listen carefully to the presented fragment and then "
                    "answer the question that follows."
                ),
                "InstitutionName": _INSTITUTION_NAME,
                "InstitutionAddress": _INSTITUTION_ADDRESS,
                "InstitutionalDepartmentName": _INSTITUTIONAL_DEPARTMENT,
                "StimulusPresentation": _STIMULUS_PRESENTATION,
            },
        ),
        (
            bids_root / "task-restingState_events.json",
            {
                "TaskName": "restingState",
                "TaskDescription": (
                    "Silent resting-state recording bookending the active "
                    "listening blocks. Participants sat quietly with no "
                    "auditory stimulus presented; used as a baseline for "
                    "the speech-evoked response analyses."
                ),
                "Instructions": ("Sit quietly and relax. No action is required."),
                "InstitutionName": _INSTITUTION_NAME,
                "InstitutionAddress": _INSTITUTION_ADDRESS,
                "InstitutionalDepartmentName": _INSTITUTIONAL_DEPARTMENT,
                "StimulusPresentation": _STIMULUS_PRESENTATION,
            },
        ),
    ]
    for path, extra in fixes:
        if not path.exists():
            logger.warning("Skipping %s — file does not exist", path)
            continue
        with open(path) as f:
            data = json.load(f)

        changed_keys = [k for k, v in extra.items() if data.get(k) != v]
        if not changed_keys:
            logger.info("%s already has all recommended keys", path.name)
            continue
        for k, v in extra.items():
            data[k] = v

        if dry_run:
            logger.info(
                "[DRY] Would add/update %d keys in %s: %s",
                len(changed_keys),
                path.name,
                changed_keys,
            )
            continue
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        logger.info(
            "Added/updated %d recommended keys in %s",
            len(changed_keys),
            path.name,
        )


def fix_events_json_units(bids_root: Path, dry_run: bool = False) -> None:
    """Fix `Unit: "seconds"` -> `Unit: "s"` in task-*_events.json.

    The BIDS validator warns that the `onset` column's `Unit` value must
    be `s`, not the full word `seconds`.
    """
    for path in sorted(bids_root.glob("task-*_events.json")):
        with open(path) as f:
            d = json.load(f)
        changed = False
        for key in ("onset", "duration"):
            if key in d and isinstance(d[key], dict):
                unit = d[key].get("Units") or d[key].get("Unit")
                if unit == "seconds":
                    # Preserve the correct BIDS key name and value
                    d[key].pop("Unit", None)
                    d[key]["Units"] = "s"
                    changed = True
        if not changed:
            continue
        if dry_run:
            logger.info("[DRY] Would fix Units in %s", path.name)
            continue
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
            f.write("\n")
        logger.info("Fixed Units in %s", path.name)


def relocate_remarks(bids_root: Path, dry_run: bool = False) -> int:
    """Move per-session `remarks/` text files out of the BIDS subject
    hierarchy and into `/code/remarks/`.

    The upstream SparrKULee release stores free-form recording notes as
    `sub-XX/ses-YY/remarks/sub-XX_ses-YY_remarks.(txt|docx)`. The BIDS
    validator rejects arbitrary `remarks/` directories inside a session
    folder. Rather than silence it with `.bidsignore` (which would hide
    the files from users), we move each file to
    `/code/remarks/sub-XX_ses-YY_remarks.(txt|docx)` so they remain
    visible and live next to the conversion script.

    Returns the number of files moved.
    """
    code_remarks = bids_root / "code" / "remarks"
    if not dry_run:
        code_remarks.mkdir(parents=True, exist_ok=True)

    moved = 0
    for remarks_dir in sorted(bids_root.glob("sub-*/ses-*/remarks")):
        if not remarks_dir.is_dir():
            continue
        for fp in sorted(remarks_dir.iterdir()):
            if not fp.is_file():
                continue
            dest = code_remarks / fp.name
            if dry_run:
                logger.info("[DRY] Would move %s -> %s", fp, dest)
            else:
                if dest.exists():
                    logger.debug("Overwriting %s", dest)
                shutil.move(str(fp), str(dest))
                logger.info("Moved %s -> code/remarks/%s", fp.name, fp.name)
            moved += 1
        # Remove the now-empty remarks/ directory so BIDS validator doesn't
        # see it.
        if not dry_run:
            try:
                remarks_dir.rmdir()
            except OSError as exc:
                logger.warning("Could not remove %s: %s", remarks_dir, exc)
    logger.info("Relocated %d remarks file(s) into code/remarks/", moved)
    return moved


def ensure_code_folder(
    bids_root: Path, script_path: Path, dry_run: bool = False
) -> None:
    """Copy this conversion script into /code/ for provenance."""
    code_dir = bids_root / "code"
    dest = code_dir / script_path.name
    if dry_run:
        logger.info("[DRY] Would copy %s -> %s", script_path, dest)
        return
    code_dir.mkdir(parents=True, exist_ok=True)
    if script_path.exists():
        shutil.copy2(script_path, dest)
        logger.info("Copied %s into code/", script_path.name)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare SparrKULee for NEMAR re-hosting",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    bids_root = args.input
    if not bids_root.exists():
        raise FileNotFoundError(f"BIDS root not found: {bids_root}")

    logger.info("Preparing SparrKULee for NEMAR re-host at %s", bids_root)
    removed = remove_restricted_subjects(bids_root, dry_run=args.dry_run)
    logger.info("Removed %d restricted subjects: %s", len(removed), removed)
    fix_participants_tsv(bids_root, dry_run=args.dry_run)
    fix_participants_json(bids_root, dry_run=args.dry_run)
    fix_dataset_description(bids_root, dry_run=args.dry_run)
    fix_readme(bids_root, dry_run=args.dry_run)
    clean_duplicate_events_tsv(bids_root, dry_run=args.dry_run)
    clean_download_artifacts(bids_root, dry_run=args.dry_run)
    fix_events_json_units(bids_root, dry_run=args.dry_run)
    fix_task_listening_eeg_sidecar(bids_root, dry_run=args.dry_run)
    fix_task_sidecars(bids_root, dry_run=args.dry_run)
    relocate_remarks(bids_root, dry_run=args.dry_run)
    # Self-deposit the conversion script into /code/ for provenance.
    script_path = Path(__file__).resolve()
    ensure_code_folder(bids_root, script_path, dry_run=args.dry_run)
    logger.info("Done.")


if __name__ == "__main__":
    main()
