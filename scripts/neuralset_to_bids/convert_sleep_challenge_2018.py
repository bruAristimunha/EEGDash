#!/usr/bin/env python3
from __future__ import annotations

"""Convert the PhysioNet/CinC Challenge 2018 sleep dataset to BIDS-EEG format.

"You Snooze, You Win" — 1,983 overnight polysomnographic (PSG) recordings from
subjects with suspected sleep apnea, collected at Massachusetts General Hospital
(MGH). 994 training + 989 test subjects. Each recording has 13 channels
(6 EEG, 1 EOG, 1 EMG, 3 respiratory, 1 SpO2, 1 ECG) at 200 Hz in WFDB format.

Training set has expert-annotated (AASM standard) sleep staging (30-second
epochs: W, N1, N2, N3, REM) and respiratory/arousal events (obstructive/central/
mixed apnea, hypopnea, RERA, spontaneous arousals, snoring arousals, PLM
arousals) in .arousal files. Test set has PSG signals only (no annotations).

Demographics: mean age 55 ± 14 years (range 18–93), 65% male.

Usage:
    python convert_sleep_challenge_2018.py --input /tmp/sleep_challenge_2018 --output /tmp/sc2018_bids
    python convert_sleep_challenge_2018.py --input /tmp/sleep_challenge_2018 --output /tmp/sc2018_bids --test-only
    python convert_sleep_challenge_2018.py --input /tmp/sleep_challenge_2018 --output /tmp/sc2018_bids --dry-run

Reference:
    Ghassemi, M.M., Moody, B.E., Lehman, L.H., Song, C., Li, Q., Sun, H.,
    Mark, R.G., Westover, M.B. & Clifford, G.D. (2018). You Snooze, You Win:
    the PhysioNet/Computing in Cardiology Challenge 2018. Computing in
    Cardiology, 45, 1-4. doi:10.22489/CinC.2018.049
    https://physionet.org/content/challenge-2018/1.0.0/
"""

import argparse
import json
import logging
import os
from collections import Counter
from pathlib import Path

import mne
import mne_bids
import numpy as np
import pandas as pd
import wfdb

logger = logging.getLogger(__name__)

SFREQ = 200.0

# Channel mapping from WFDB to BIDS types
CHANNEL_TYPES_ALL = {
    "F3-M2": "eeg",
    "F4-M1": "eeg",
    "C3-M2": "eeg",
    "C4-M1": "eeg",
    "O1-M2": "eeg",
    "O2-M1": "eeg",
    "E1-M2": "eog",
    "Chin1-Chin2": "emg",
    "ABD": "misc",
    "CHEST": "misc",
    "AIRFLOW": "misc",
    "SaO2": "misc",
    "ECG": "ecg",
}

# Sleep stage mapping
STAGE_MAP = {
    "W": "Wake",
    "N1": "N1",
    "N2": "N2",
    "N3": "N3",
    "R": "REM",
}

# Arousal/respiratory event types (all types found in the 994 training subjects)
AROUSAL_TYPES = {
    "arousal_rera": "Respiratory effort-related arousal (RERA)",
    "arousal_spontaneous": "Spontaneous arousal",
    "arousal_snore": "Snoring arousal",
    "arousal_plm": "Periodic leg movement arousal",
    "resp_obstructiveapnea": "Obstructive apnea",
    "resp_centralapnea": "Central apnea",
    "resp_hypopnea": "Hypopnea",
    "resp_mixedapnea": "Mixed apnea",
    "resp_partialobstructive": "Partial airway obstruction",
    "resp_hypoventilation": "Hypoventilation",
    "resp_cheynestokesbreath": "Cheyne-Stokes breathing",
    "arousal_bruxism": "Bruxism (teeth grinding) arousal",
    "arousal_noise": "Noise-related arousal",
}


def load_wfdb_as_raw(sub_dir: str, record_name: str) -> tuple[mne.io.RawArray, dict]:
    """Load a WFDB record and return MNE RawArray + metadata dict."""
    rec_path = os.path.join(sub_dir, record_name)
    record = wfdb.rdrecord(rec_path)

    # Build channel types list
    ch_types = []
    for ch in record.sig_name:
        ch_types.append(CHANNEL_TYPES_ALL.get(ch, "misc"))

    # Convert to volts
    data = record.p_signal.T.copy()
    units = np.array(record.units)
    data[units == "uV"] /= 1e6
    data[units == "mV"] /= 1e3

    info = mne.create_info(record.sig_name, record.fs, ch_types, verbose=False)
    raw = mne.io.RawArray(data, info, verbose=False)

    metadata = {
        "duration_h": round(record.sig_len / record.fs / 3600, 2),
        "n_channels": record.n_sig,
        "sfreq": record.fs,
    }
    return raw, metadata


def parse_arousal_annotations(
    sub_dir: str, record_name: str
) -> tuple[mne.Annotations, dict]:
    """Parse .arousal file into MNE Annotations and summary stats."""
    rec_path = os.path.join(sub_dir, record_name)

    try:
        annots = wfdb.rdann(rec_path, "arousal")
    except Exception:
        return mne.Annotations([], [], []), {}

    onsets = annots.sample / annots.fs
    notes = np.array(annots.aux_note)
    channels = annots.chan

    new_onset, new_duration, new_description = [], [], []
    sleep_stages = Counter()
    arousal_counts = Counter()

    for ch in set(channels):
        mask = channels == ch
        ch_onsets = onsets[mask]
        ch_notes = notes[mask]

        # Separate sleep stages from arousal events
        stage_mask = np.array([n in STAGE_MAP for n in ch_notes])
        event_mask = np.array([n.startswith("(") or n.endswith(")") for n in ch_notes])

        # Sleep stages — consecutive, 30s-ish epochs
        if stage_mask.any():
            s_onsets = ch_onsets[stage_mask]
            s_notes = ch_notes[stage_mask]
            s_durations = np.concatenate([np.diff(s_onsets), [30.0]])
            s_durations = np.maximum(s_durations, 0)

            for onset, dur, desc in zip(s_onsets, s_durations, s_notes):
                stage = STAGE_MAP.get(desc, desc)
                new_onset.append(onset)
                new_duration.append(dur)
                new_description.append(stage)
                sleep_stages[stage] += 1

        # Arousal/respiratory events — paired (start and end)
        # Events may overlap: (A ... (B ... A) ... B)
        # Use a stack-like approach to find matching close for each open
        if event_mask.any():
            e_onsets = ch_onsets[event_mask]
            e_notes = ch_notes[event_mask]

            # Build lookup: for each opening, find its matching close
            open_stack = []  # list of (event_type, onset, index)
            pairs = {}  # open_index -> close_index

            for idx, note in enumerate(e_notes):
                if note.startswith("("):
                    open_stack.append((note[1:], e_onsets[idx], idx))
                elif note.endswith(")"):
                    close_type = note[:-1]
                    # Find the most recent matching open
                    for j in range(len(open_stack) - 1, -1, -1):
                        if open_stack[j][0] == close_type:
                            pairs[open_stack[j][2]] = idx
                            open_stack.pop(j)
                            break

            for idx, note in enumerate(e_notes):
                if note.startswith("("):
                    event_type = note[1:]
                    onset = e_onsets[idx]
                    if idx in pairs:
                        duration = e_onsets[pairs[idx]] - onset
                    else:
                        duration = 0
                    new_onset.append(onset)
                    new_duration.append(max(duration, 0))
                    new_description.append(event_type)
                    arousal_counts[event_type] += 1

    mne_annots = mne.Annotations(
        new_onset, new_duration, new_description, orig_time=None
    )

    stats = {
        "n_wake": sleep_stages.get("Wake", 0),
        "n_n1": sleep_stages.get("N1", 0),
        "n_n2": sleep_stages.get("N2", 0),
        "n_n3": sleep_stages.get("N3", 0),
        "n_rem": sleep_stages.get("REM", 0),
        "n_arousal_rera": arousal_counts.get("arousal_rera", 0),
        "n_arousal_spontaneous": arousal_counts.get("arousal_spontaneous", 0),
        "n_arousal_snore": arousal_counts.get("arousal_snore", 0),
        "n_arousal_plm": arousal_counts.get("arousal_plm", 0),
        "n_resp_obstructive": arousal_counts.get("resp_obstructiveapnea", 0),
        "n_resp_central": arousal_counts.get("resp_centralapnea", 0),
        "n_resp_hypopnea": arousal_counts.get("resp_hypopnea", 0),
        "n_resp_mixed": arousal_counts.get("resp_mixedapnea", 0),
    }
    return mne_annots, stats


def write_dataset_description(bids_root: Path):
    desc = {
        "Name": "You Snooze You Win: PhysioNet/CinC Challenge 2018 PSG",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "Open Data Commons Attribution License v1.0",
        "Authors": [
            "Mohammad M. Ghassemi",
            "Benjamin E. Moody",
            "Li-wei H. Lehman",
            "Christopher Song",
            "Qiao Li",
            "Haoqi Sun",
            "Roger G. Mark",
            "M. Brandon Westover",
            "Gari D. Clifford",
        ],
        "Funding": [
            "National Institute of Biomedical Imaging and Bioengineering (NIBIB) U24EB037545",
            "National Institute of Biomedical Imaging and Bioengineering (NIBIB) R01EB030362",
            "The MathWorks (equipment sponsorship)",
        ],
        "DatasetDOI": "doi:10.13026/6phb-r450",
        "ReferencesAndLinks": [
            "https://physionet.org/content/challenge-2018/1.0.0/",
            "https://doi.org/10.22489/CinC.2018.049",
            "https://doi.org/10.13026/6phb-r450",
        ],
        "HowToAcknowledge": (
            "Please cite: Ghassemi, M.M., Moody, B.E., Lehman, L.H., Song, C., "
            "Li, Q., Sun, H., Mark, R.G., Westover, M.B. & Clifford, G.D. (2018). "
            "You Snooze, You Win: the PhysioNet/Computing in Cardiology Challenge "
            "2018. Computing in Cardiology, 45, 1-4. "
            "And: Goldberger, A. et al. (2000). PhysioBank, PhysioToolkit, "
            "PhysioNet. Circulation, 101(23), e215-e220."
        ),
        "SourceDatasets": [
            {"URL": "https://physionet.org/content/challenge-2018/1.0.0/"}
        ],
        "GeneratedBy": [
            {
                "Name": "convert_sleep_challenge_2018.py (EEGDash)",
                "Description": "Converted from WFDB (.mat/.hea) + arousal annotations to BIDS-EEG.",
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
        "HEDVersion": "8.2.0",
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    readme = """\
You Snooze You Win: PhysioNet/CinC Challenge 2018 PSG
=======================================================

Overview
--------
1,983 overnight polysomnographic (PSG) recordings from subjects monitored at
the Massachusetts General Hospital (MGH) sleep laboratory for sleep disorder
diagnosis. The dataset was created for the PhysioNet/Computing in Cardiology
Challenge 2018 on automatic arousal detection.

- Training set: 994 subjects (with expert annotations)
- Test set: 989 subjects (PSG signals only, no annotations)
- Demographics: mean age 55 +/- 14 years (range 18-93), 65% male, 35% female
- Clinical population: subjects with suspected obstructive sleep apnea

Channels (13 total, all at 200 Hz)
-----------------------------------
- EEG (6): F3-M2, F4-M1, C3-M2, C4-M1, O1-M2, O2-M1
  Referential montage against contralateral mastoids (M1/M2)
- EOG (1): E1-M2 (left electrooculogram)
- EMG (1): Chin1-Chin2 (submental chin electromyogram)
- Respiratory (3): ABD (abdominal effort), CHEST (thoracic effort),
  AIRFLOW (nasal/oral airflow)
- SpO2 (1): SaO2 (pulse oximetry, resampled to 200 Hz)
- ECG (1): ECG (single-lead electrocardiogram)

Annotations (training set only, in events.tsv)
------------------------------------------------
Sleep staging (AASM standard, 30-second contiguous epochs):
  Wake, N1, N2, N3, REM

Respiratory events (with onset and duration):
  resp_obstructiveapnea  — complete upper airway obstruction
  resp_centralapnea      — absent respiratory effort
  resp_mixedapnea        — combined obstructive + central
  resp_hypopnea          — partial airway obstruction (>=30% flow reduction)

Arousal events:
  arousal_rera           — respiratory effort-related arousal
  arousal_spontaneous    — spontaneous cortical arousal
  arousal_snore          — snoring-related arousal
  arousal_plm            — periodic leg movement arousal

Participants metadata (in participants.tsv)
--------------------------------------------
Per-subject: age, sex, split (training/test), recording duration, sleep
architecture (epoch counts per stage), and respiratory/arousal event counts.

Sessions
--------
- ses-training: 994 subjects with PSG + annotations
- ses-test: 989 subjects with PSG only (no annotations)

Notes
-----
- Original format: WFDB (.mat + .hea + .arousal)
- All signals originally at 200 Hz; SaO2 was resampled to match
- Annotators: certified sleep technologists at MGH, following AASM manual
- Updated arousal annotations (new-arousals.zip) supersede originals

Reference
---------
Ghassemi, M.M., Moody, B.E., Lehman, L.H., Song, C., Li, Q., Sun, H.,
Mark, R.G., Westover, M.B. & Clifford, G.D. (2018). You Snooze, You Win:
the PhysioNet/Computing in Cardiology Challenge 2018. Computing in
Cardiology, 45, 1-4. doi:10.22489/CinC.2018.049

Goldberger, A. et al. (2000). PhysioBank, PhysioToolkit, and PhysioNet:
Components of a new research resource for complex physiologic signals.
Circulation, 101(23), e215-e220.
https://physionet.org/content/challenge-2018/1.0.0/
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def _find_data_dir(input_dir: Path) -> Path:
    """Locate the pc18-sleep-data directory."""
    for candidate in [input_dir / "pc18-sleep-data", input_dir]:
        if (candidate / "training").exists():
            return candidate
    raise FileNotFoundError(f"Cannot find training/ directory under {input_dir}")


def _load_demographics(input_dir: Path) -> dict:
    """Load age-sex.csv into a lookup dict keyed by record name."""
    for candidate in [
        input_dir / "age-sex.csv",
        input_dir / "pc18-sleep-data" / "age-sex.csv",
    ]:
        if candidate.exists():
            df = pd.read_csv(candidate)
            demo = {}
            for _, row in df.iterrows():
                demo[row["Record"]] = {
                    "age": int(row["Age"]),
                    "sex": row["Sex"].upper() if isinstance(row["Sex"], str) else "n/a",
                }
            logger.info("Loaded demographics for %d records", len(demo))
            return demo
    logger.warning("age-sex.csv not found")
    return {}


def _enrich_events_json(events_json_path: Path):
    """Add Levels descriptions to events.json for trial_type."""
    if not events_json_path.exists():
        return
    with open(events_json_path) as f:
        events_meta = json.load(f)

    events_meta["trial_type"] = {
        "Description": "Event type: sleep stage (30-second epoch) or arousal/respiratory event",
        "Levels": {
            "Wake": "Wakefulness (AASM stage W)",
            "N1": "NREM stage 1 — light sleep",
            "N2": "NREM stage 2 — sleep spindles and K-complexes",
            "N3": "NREM stage 3 — slow-wave (deep) sleep",
            "REM": "Rapid eye movement sleep",
            "arousal_rera": "Respiratory effort-related arousal (RERA)",
            "arousal_spontaneous": "Spontaneous cortical arousal",
            "arousal_snore": "Snoring-related arousal",
            "arousal_plm": "Periodic leg movement arousal",
            "resp_obstructiveapnea": "Obstructive apnea — complete upper airway obstruction",
            "resp_centralapnea": "Central apnea — absent respiratory effort",
            "resp_mixedapnea": "Mixed apnea — combined obstructive and central",
            "resp_hypopnea": "Hypopnea — partial airway obstruction (>=30% flow reduction)",
            "resp_partialobstructive": "Partial airway obstruction",
            "resp_hypoventilation": "Hypoventilation — inadequate ventilation",
            "resp_cheynestokesbreath": "Cheyne-Stokes breathing — cyclic crescendo-decrescendo pattern",
            "arousal_bruxism": "Bruxism (teeth grinding) arousal",
            "arousal_noise": "Noise-related arousal",
        },
    }
    events_meta["StimulusPresentation"] = {
        "OperatingSystem": "n/a",
        "SoftwareName": "n/a",
        "SoftwareVersion": "n/a",
    }
    with open(events_json_path, "w") as f:
        json.dump(events_meta, f, indent=2)
        f.write("\n")


def _enrich_sidecar(sidecar_path: Path, record_name: str, split: str):
    """Enrich the EEG sidecar JSON with metadata."""
    if not sidecar_path.exists():
        return
    with open(sidecar_path) as f:
        sidecar = json.load(f)

    task_desc = (
        "Overnight clinical polysomnography for sleep apnea evaluation at "
        "Massachusetts General Hospital. Subjects slept naturally while 13 "
        "channels of PSG data were recorded. "
    )
    if split == "training":
        task_desc += (
            "Expert-annotated by certified sleep technologists following AASM "
            "manual: 30-second sleep staging and respiratory/arousal events."
        )
    else:
        task_desc += "Test set — PSG signals only, no expert annotations."

    sidecar.update(
        {
            "TaskName": "sleep",
            "TaskDescription": task_desc,
            "Instructions": "Sleep naturally",
            "InstitutionName": "Massachusetts General Hospital",
            "InstitutionAddress": "55 Fruit Street, Boston, MA 02114, USA",
            "InstitutionalDepartmentName": (
                "Computational Clinical Neurophysiology Laboratory (CCNL) "
                "and Clinical Data Animation Laboratory (CDAC)"
            ),
            "PowerLineFrequency": 60,
            "EEGReference": "Contralateral mastoid (M1/M2)",
            "EEGPlacementScheme": "10-20 subset (F3, F4, C3, C4, O1, O2)",
            "RecordingType": "continuous",
            "SoftwareFilters": "n/a",
            "HardwareFilters": "n/a",
            "Manufacturer": "n/a",
            "ManufacturersModelName": "n/a",
            "CapManufacturer": "n/a",
            "CapManufacturersModelName": "n/a",
            "SoftwareVersions": "n/a",
            "DeviceSerialNumber": "n/a",
            "SubjectArtefactDescription": "n/a",
            "MISCChannelCount": 4,
            "CogAtlasID": "n/a",
            "CogPOID": "n/a",
            "OriginalRecord": record_name,
            "OriginalFormat": "WFDB (.mat + .hea + .arousal)",
        }
    )
    with open(sidecar_path, "w") as f:
        json.dump(sidecar, f, indent=2)
        f.write("\n")


def _convert_split(
    split_dir: Path,
    output_dir: Path,
    split: str,
    demographics: dict,
    max_subjects: int | None,
    *,
    overwrite: bool,
    verbose: bool,
) -> tuple[list[dict], int, int]:
    """Convert one split (training or test). Returns (participants, n_ok, n_fail)."""
    prefix = "tr" if split == "training" else "te"
    subjects = sorted(
        [
            d
            for d in os.listdir(split_dir)
            if os.path.isdir(os.path.join(split_dir, d)) and d.startswith(prefix)
        ]
    )
    logger.info("Found %d %s subjects", len(subjects), split)

    if max_subjects:
        subjects = subjects[:max_subjects]

    participants = []
    n_ok = 0
    n_fail = 0

    for i, record_name in enumerate(subjects):
        sub_dir = str(split_dir / record_name)
        sub_id = record_name.replace("-", "")

        try:
            # 1. Load WFDB signal
            raw, rec_meta = load_wfdb_as_raw(sub_dir, record_name)

            # 2. Parse annotations (training only)
            ann_stats = {}
            if split == "training":
                annots, ann_stats = parse_arousal_annotations(sub_dir, record_name)
                if len(annots) > 0:
                    raw.set_annotations(annots)

            # 3. Write BIDS
            bids_path = mne_bids.BIDSPath(
                subject=sub_id,
                session=split,
                task="sleep",
                datatype="eeg",
                root=output_dir,
            )

            mne_bids.write_raw_bids(
                raw,
                bids_path,
                overwrite=overwrite,
                verbose=verbose,
                allow_preload=True,
                format="BDF",
            )

            # 4. Enrich sidecar and events metadata
            sf = bids_path.copy().update(suffix="eeg", extension=".json").fpath
            _enrich_sidecar(sf, record_name, split)
            ef = bids_path.copy().update(suffix="events", extension=".json").fpath
            _enrich_events_json(ef)

            # 5. Build participant row
            demo = demographics.get(record_name, {"age": "n/a", "sex": "n/a"})
            participant = {
                "participant_id": f"sub-{sub_id}",
                "age": demo["age"],
                "sex": demo["sex"],
                "split": split,
                "record": record_name,
                "duration_h": rec_meta["duration_h"],
                "n_wake": ann_stats.get("n_wake", 0),
                "n_n1": ann_stats.get("n_n1", 0),
                "n_n2": ann_stats.get("n_n2", 0),
                "n_n3": ann_stats.get("n_n3", 0),
                "n_rem": ann_stats.get("n_rem", 0),
                "n_arousal_rera": ann_stats.get("n_arousal_rera", 0),
                "n_arousal_spontaneous": ann_stats.get("n_arousal_spontaneous", 0),
                "n_arousal_snore": ann_stats.get("n_arousal_snore", 0),
                "n_arousal_plm": ann_stats.get("n_arousal_plm", 0),
                "n_resp_obstructive": ann_stats.get("n_resp_obstructive", 0),
                "n_resp_central": ann_stats.get("n_resp_central", 0),
                "n_resp_hypopnea": ann_stats.get("n_resp_hypopnea", 0),
                "n_resp_mixed": ann_stats.get("n_resp_mixed", 0),
            }
            participants.append(participant)

            n_ok += 1
            if (i + 1) % 50 == 0:
                logger.info(
                    "[%s] Progress: %d/%d (%.0f%%)",
                    split,
                    i + 1,
                    len(subjects),
                    (i + 1) / len(subjects) * 100,
                )

        except Exception as exc:
            logger.warning("FAILED %s: %s", record_name, exc)
            n_fail += 1

    return participants, n_ok, n_fail


def convert_sleep_challenge_2018(
    input_dir: Path,
    output_dir: Path,
    max_subjects: int | None = None,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
    training_only: bool = False,
    test_only: bool = False,
):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data_dir = _find_data_dir(input_dir)
    demographics = _load_demographics(input_dir)

    # Determine which splits to convert
    splits = []
    if not test_only:
        splits.append(("training", data_dir / "training"))
    if not training_only:
        test_dir = data_dir / "test"
        if test_dir.exists():
            splits.append(("test", test_dir))
        else:
            logger.warning("Test directory not found at %s — skipping", test_dir)

    if dry_run:
        for split_name, split_dir in splits:
            prefix = "tr" if split_name == "training" else "te"
            subjects = [
                d
                for d in os.listdir(split_dir)
                if os.path.isdir(os.path.join(split_dir, d)) and d.startswith(prefix)
            ]
            print(f"  {split_name}: {len(subjects)} subjects")
        return

    write_dataset_description(output_dir)
    write_readme(output_dir)

    all_participants = []
    total_ok = 0
    total_fail = 0

    for split_name, split_dir in splits:
        participants, n_ok, n_fail = _convert_split(
            split_dir,
            output_dir,
            split_name,
            demographics,
            max_subjects,
            overwrite=overwrite,
            verbose=verbose,
        )
        all_participants.extend(participants)
        total_ok += n_ok
        total_fail += n_fail

    # Write participants.tsv
    pdf = pd.DataFrame(all_participants)
    pdf.to_csv(output_dir / "participants.tsv", sep="\t", index=False)

    # Write participants.json
    p_desc = {
        "participant_id": {"Description": "Subject ID (derived from WFDB record name)"},
        "age": {"Description": "Age at time of recording", "Units": "years"},
        "sex": {
            "Description": "Biological sex",
            "Levels": {"M": "Male", "F": "Female"},
        },
        "split": {
            "Description": "Challenge split",
            "Levels": {
                "training": "Training set (with expert sleep staging and arousal annotations)",
                "test": "Test set (PSG signals only, no annotations)",
            },
        },
        "record": {"Description": "Original WFDB record name from PhysioNet"},
        "duration_h": {"Description": "Recording duration", "Units": "hours"},
        "n_wake": {"Description": "Number of 30-second Wake epochs (training only)"},
        "n_n1": {"Description": "Number of 30-second N1 (NREM stage 1) epochs"},
        "n_n2": {"Description": "Number of 30-second N2 (NREM stage 2) epochs"},
        "n_n3": {"Description": "Number of 30-second N3 (slow-wave sleep) epochs"},
        "n_rem": {"Description": "Number of 30-second REM epochs"},
        "n_arousal_rera": {
            "Description": "Number of respiratory effort-related arousal (RERA) events",
        },
        "n_arousal_spontaneous": {
            "Description": "Number of spontaneous arousal events"
        },
        "n_arousal_snore": {"Description": "Number of snoring-related arousal events"},
        "n_arousal_plm": {
            "Description": "Number of periodic leg movement arousal events"
        },
        "n_resp_obstructive": {"Description": "Number of obstructive apnea events"},
        "n_resp_central": {"Description": "Number of central apnea events"},
        "n_resp_hypopnea": {"Description": "Number of hypopnea events"},
        "n_resp_mixed": {"Description": "Number of mixed apnea events"},
    }
    with open(output_dir / "participants.json", "w") as f:
        json.dump(p_desc, f, indent=2)
        f.write("\n")

    logger.info(
        "Done: %d ok, %d failed (across %d splits)", total_ok, total_fail, len(splits)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert PhysioNet/CinC Challenge 2018 to BIDS",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument(
        "--max-subjects",
        "-n",
        type=int,
        default=None,
        help="Max subjects per split (for testing)",
    )
    parser.add_argument(
        "--training-only",
        action="store_true",
        help="Convert training set only (994 subjects with annotations)",
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Convert test set only (989 subjects, no annotations)",
    )
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.verbose:
        mne.set_log_level("WARNING")

    convert_sleep_challenge_2018(
        args.input,
        args.output,
        args.max_subjects,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
        training_only=args.training_only,
        test_only=args.test_only,
    )


if __name__ == "__main__":
    main()
