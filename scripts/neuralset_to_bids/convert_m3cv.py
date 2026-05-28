#!/usr/bin/env python3
from __future__ import annotations

"""Convert the M3CV dataset (Huang et al., NeuroImage 2022) to BIDS-EEG format.

The M3CV dataset contains pre-epoched EEG from 106 subjects (95 with 2 sessions)
across 6 paradigms and 13 task types. Each epoch is a .mat file with shape
(65, 1000) at 250 Hz — 64 EEG channels + 1 marker channel, 4 seconds per epoch.

This script reconstructs pseudo-continuous recordings per subject/session/task
by concatenating epochs, derives events from the marker channel, and writes
BIDS-compliant output using mne_bids.

Usage:
    python convert_m3cv.py --input /path/to/m3cv --output /path/to/bids_output
    python convert_m3cv.py --input /path/to/m3cv --output /path/to/bids_output --subjects sub001 sub002
    python convert_m3cv.py --input /path/to/m3cv --output /path/to/bids_output --dry-run

References:
    Huang, G. et al. (2022). M3CV: A multi-subject, multi-session, and
    multi-task database for EEG-based biometrics challenge. NeuroImage, 264, 119666.
    https://doi.org/10.1016/j.neuroimage.2022.119666
"""

import argparse
import json
import logging
from pathlib import Path

import mne
import mne_bids
import numpy as np
import pandas as pd
import scipy.io as sio

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

SFREQ = 250.0
N_EEG_CHANNELS = 64
MARKER_CHANNEL_IDX = 64
SAMPLES_PER_EPOCH = 1000
EPOCH_DURATION_S = SAMPLES_PER_EPOCH / SFREQ  # 4.0 seconds

# Data is stored as float32 in microvolts. MNE expects volts internally.
MICROVOLT_TO_VOLT = 1e-6

CHANNEL_NAMES = [
    "FP1",
    "FP2",
    "F3",
    "F4",
    "C3",
    "C4",
    "P3",
    "P4",
    "O1",
    "O2",
    "F7",
    "F8",
    "T7",
    "T8",
    "P7",
    "P8",
    "FZ",
    "CZ",
    "PZ",
    "FC1",
    "FC2",
    "CP1",
    "CP2",
    "FC5",
    "FC6",
    "CP5",
    "CP6",
    "FT9",
    "FT10",
    "TP9",
    "TP10",
    "F1",
    "F2",
    "C1",
    "C2",
    "P1",
    "P2",
    "AF3",
    "AF4",
    "FC3",
    "FC4",
    "CP3",
    "CP4",
    "PO3",
    "PO4",
    "F5",
    "F6",
    "C5",
    "C6",
    "P5",
    "P6",
    "AF7",
    "AF8",
    "FT7",
    "FT8",
    "TP7",
    "TP8",
    "PO7",
    "PO8",
    "FPZ",
    "CPZ",
    "POZ",
    "OZ",
    "FCZ",
]

CHANNEL_TYPES = ["eeg"] * N_EEG_CHANNELS

# ── Task definitions ─────────────────────────────────────────────────────────
# task_code → (bids_label, description, paradigm, stimulus_description)

TASK_MAP = {
    1: (
        "restEC",
        "Resting state eyes closed, 1 min per run (runs 01 & 14)",
        "resting-state",
        "No stimulus; eyes closed, fixating on LED (off state)",
    ),
    2: (
        "restEO",
        "Resting state eyes open, 1 min per run (runs 02 & 15)",
        "resting-state",
        "No stimulus; eyes open, fixating straight ahead with minimal blinking",
    ),
    3: (
        "vep",
        "Visual evoked potential, 50 ms LED flash, ISI 2-4 s, 30 trials/run (runs 04 & 11)",
        "transient-state",
        "3 W LED (TES-1332A measured), 2 cm diameter circular shield, 45 cm from eyes, "
        "1074 Lux mean intensity, 50 ms duration; delivered via Arduino Uno",
    ),
    4: (
        "aep",
        "Auditory evoked potential, 1000 Hz tone 50 ms, ISI 2-4 s, 30 trials/run (runs 04 & 11)",
        "transient-state",
        "1000 Hz pure tone, 50 ms duration, 75 dB SPL average; Nokia WH-102 headphones; "
        "delivered via Arduino Uno",
    ),
    5: (
        "sep",
        "Somatosensory evoked potential, vibration on left hand 50 ms, ISI 2-4 s, "
        "30 trials/run (runs 04 & 11)",
        "transient-state",
        "1027 disk vibration motor on left hand, 50 ms duration, 3 W rated power, "
        "80% efficiency, 10 mm x 2.7 mm; delivered via Arduino Uno",
    ),
    6: (
        "ssvep",
        "Steady-state visual evoked potential, 10 Hz LED, 1 min (run 05)",
        "steady-state",
        "10 Hz LED flickering (same 3 W LED as VEP), continuous for 1 min",
    ),
    7: (
        "ssaep",
        "Steady-state auditory evoked potential, 45.38 Hz, 2 min (run 09)",
        "steady-state",
        "45.38 Hz amplitude-modulated auditory tone via Nokia WH-102, continuous for 2 min",
    ),
    8: (
        "sssep",
        "Steady-state somatosensory evoked potential, 22.04 Hz vibration, 2 min (run 12)",
        "steady-state",
        "22.04 Hz vibration motor (same 1027 disk motor as SEP) on left hand, "
        "continuous for 2 min",
    ),
    9: (
        "p300",
        "P300 visual oddball — target only (30 target / 600 total), 80 ms, ISI 200 ms "
        "(run 07). Nontarget P300 epochs (570 trials) not distributed.",
        "cognitive-oddball",
        "Red square (target) and white square (nontarget) on black background, "
        "300x300 pixels, 80 ms duration, ISI 200 ms, 5% target probability; "
        "subjects counted red squares; presented via Psychtoolbox-3",
    ),
    10: (
        "motorFoot",
        "Motor execution — right ankle dorsiflexion, 3 s cue duration, 20 trials/run "
        "(runs 03, 06, 10, 13)",
        "motor-execution",
        "Visual cue (white 300x300 px square via Psychtoolbox-3), executed movement at "
        "~2x/sec, ~80% MVC, 3 s duration until cue offset, no feedback or metronome",
    ),
    11: (
        "motorRHand",
        "Motor execution — right hand grip, 3 s cue duration, 20 trials/run "
        "(runs 03, 06, 10, 13)",
        "motor-execution",
        "Visual cue (white 300x300 px square via Psychtoolbox-3), executed grip at "
        "~2x/sec, ~80% MVC, 3 s duration until cue offset, no feedback or metronome",
    ),
    12: (
        "motorLHand",
        "Motor execution — left hand grip, 3 s cue duration, 20 trials/run "
        "(runs 03, 06, 10, 13)",
        "motor-execution",
        "Visual cue (white 300x300 px square via Psychtoolbox-3), executed grip at "
        "~2x/sec, ~80% MVC, 3 s duration until cue offset, no feedback or metronome",
    ),
    13: (
        "ssvepSA",
        "SSVEP with selective attention — 6 simultaneous frequencies "
        "(7, 8, 9, 11, 13, 15 Hz), 12 segments of 10 s each (run 08). "
        "Each class has 12 trials across segments.",
        "ssvep-selective-attention",
        "Six white 300x300 px squares flashing simultaneously at 7/8/9/11/13/15 Hz; "
        "target square turns red 200 ms, 500 ms delay, then 10 s flicker; "
        "covert attention to target; presented via Psychtoolbox-3",
    ),
}

# Marker channel patterns
STIMULUS_AT_499 = {3, 4, 5, 9}  # Transient + P300: stimulus at sample 499 (~1.996s)
STIMULUS_AT_0 = {10, 11, 12}  # Motor: cue at sample 0
CONTINUOUS_TASKS = {1, 2, 6, 7, 8, 13}  # Resting & steady-state

# Expected epoch counts per subject per session (from paper protocol)
EXPECTED_EPOCHS = {
    1: 30,
    2: 30,
    3: 60,
    4: 60,
    5: 60,
    6: 15,
    7: 30,
    8: 30,
    9: 30,
    10: 80,
    11: 80,
    12: 80,
    13: 24,
}

# Paradigm grouping for enriched events
PARADIGM_NAMES = {
    "resting-state": "Resting state (eyes open/closed)",
    "transient-state": "Transient sensory evoked potentials (VEP/AEP/SEP)",
    "steady-state": "Steady-state sensory evoked potentials (SSVEP/SSAEP/SSSEP)",
    "cognitive-oddball": "P300 visual oddball (target trials only)",
    "motor-execution": "Motor execution (foot/right hand/left hand)",
    "ssvep-selective-attention": "SSVEP with selective attention (6 frequencies)",
}


# ── Data loading ─────────────────────────────────────────────────────────────


def load_metadata(input_dir: Path) -> pd.DataFrame:
    """Load and combine all CSV metadata files."""
    frames = []
    for csv_name, set_name in [
        ("Enrollment_Info.csv", "Enrollment"),
        ("Calibration_Info.csv", "Calibration"),
        ("Testing_Info.csv", "Testing"),
    ]:
        csv_path = input_dir / csv_name
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            df["Set"] = set_name
            frames.append(df)
            logger.info("Loaded %s: %d epochs", csv_name, len(df))
    if not frames:
        raise FileNotFoundError(
            f"No M3CV CSV files found in {input_dir}. "
            f"Expected Enrollment_Info.csv, Calibration_Info.csv, or Testing_Info.csv"
        )
    return pd.concat(frames, ignore_index=True)


def load_epoch(mat_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a single epoch .mat file.

    Returns (eeg_data, marker) where eeg_data is (64, 1000) and marker is (1000,).
    Raises ValueError if shape is unexpected.
    """
    data = sio.loadmat(str(mat_path))["epoch_data"]
    if data.shape != (65, SAMPLES_PER_EPOCH):
        raise ValueError(
            f"Unexpected shape {data.shape} in {mat_path} "
            f"(expected ({65}, {SAMPLES_PER_EPOCH}))"
        )
    eeg = data[:N_EEG_CHANNELS]  # (64, 1000)
    marker = data[MARKER_CHANNEL_IDX]  # (1000,)
    return eeg, marker


def build_concatenated_raw(
    epochs_df: pd.DataFrame,
    input_dir: Path,
) -> tuple[mne.io.RawArray, np.ndarray, dict, list[str]]:
    """Concatenate all epochs for one subject/session/task into a Raw object.

    Returns (raw, events_array, event_id_map, epoch_ids).
    """
    epoch_list = []
    marker_list = []
    epoch_ids = []

    # Each epoch may be in a different Set (folder)
    n_skipped = 0
    for row in epochs_df.itertuples(index=False):
        mat_path = input_dir / row.Set / f"{row.EpochID}.mat"
        try:
            eeg, marker = load_epoch(mat_path)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            logger.warning("Skipping %s: %s", row.EpochID, exc)
            n_skipped += 1
            continue
        epoch_list.append(eeg)
        marker_list.append(marker)
        epoch_ids.append(row.EpochID)

    if not epoch_list:
        raise RuntimeError(f"No valid epochs loaded (all {len(epochs_df)} skipped)")
    if n_skipped:
        logger.warning("Skipped %d/%d epochs", n_skipped, len(epochs_df))

    # Concatenate: (64, n_epochs * 1000)
    eeg_concat = np.concatenate(epoch_list, axis=1)
    markers_concat = np.concatenate(marker_list)

    # Validate marker channel against expected pattern
    task_code = int(epochs_df.iloc[0]["Task"])
    _validate_markers(markers_concat, task_code, len(epoch_list))

    # Sanity-check amplitude range before unit conversion
    amp_median = np.median(np.abs(eeg_concat))
    if amp_median < 0.01 or amp_median > 5000:
        logger.warning(
            "Unusual amplitude range (median |x| = %.2f) — "
            "data may not be in microvolts",
            amp_median,
        )

    # Scale to volts (data is in microvolts from BrainAmp preprocessing)
    eeg_concat = eeg_concat * MICROVOLT_TO_VOLT

    # Create MNE info and Raw
    info = mne.create_info(
        ch_names=CHANNEL_NAMES,
        sfreq=SFREQ,
        ch_types=CHANNEL_TYPES,
    )
    raw = mne.io.RawArray(eeg_concat, info, verbose=False)

    # Set montage — map M3CV uppercase names to standard_1005 mixed-case names
    montage = mne.channels.make_standard_montage("standard_1005")
    montage_lookup = {ch.upper(): ch for ch in montage.ch_names}
    rename_map = {}
    for ch in raw.ch_names:
        if ch.upper() in montage_lookup and ch != montage_lookup[ch.upper()]:
            rename_map[ch] = montage_lookup[ch.upper()]
    if rename_map:
        raw.rename_channels(rename_map)
    raw.set_montage(montage, on_missing="warn")

    # Derive events from epoch structure
    events, event_id = _derive_events(markers_concat, task_code, len(epoch_list))

    return raw, events, event_id, epoch_ids


def _validate_markers(
    markers: np.ndarray,
    task_code: int,
    n_epochs: int,
):
    """Validate that the marker channel matches expected patterns."""
    for i in range(n_epochs):
        chunk = markers[i * SAMPLES_PER_EPOCH : (i + 1) * SAMPLES_PER_EPOCH]
        if task_code in CONTINUOUS_TASKS:
            expected_val = task_code
            if not np.all(chunk == expected_val):
                uniq = np.unique(chunk)
                logger.debug(
                    "Epoch %d task %d: expected constant %d, got %s",
                    i,
                    task_code,
                    expected_val,
                    uniq,
                )
        elif task_code in STIMULUS_AT_499:
            if chunk[499] != task_code:
                logger.debug(
                    "Epoch %d task %d: expected marker=%d at sample 499, got %.0f",
                    i,
                    task_code,
                    task_code,
                    chunk[499],
                )
        elif task_code in STIMULUS_AT_0:
            if chunk[0] != task_code:
                logger.debug(
                    "Epoch %d task %d: expected marker=%d at sample 0, got %.0f",
                    i,
                    task_code,
                    task_code,
                    chunk[0],
                )


def _derive_events(
    markers: np.ndarray,
    task_code: int,
    n_epochs: int,
) -> tuple[np.ndarray, dict]:
    """Derive MNE-style events array from the marker channel.

    Returns (events, event_id) where events is (n_events, 3) array.
    """
    task_label = TASK_MAP[task_code][0]
    events = []
    event_id = {}

    if task_code in CONTINUOUS_TASKS:
        event_name = f"segment/{task_label}"
        event_id[event_name] = task_code
        for i in range(n_epochs):
            sample = i * SAMPLES_PER_EPOCH
            events.append([sample, 0, task_code])

    elif task_code in STIMULUS_AT_499:
        event_name = f"stimulus/{task_label}"
        event_id[event_name] = task_code
        for i in range(n_epochs):
            sample = i * SAMPLES_PER_EPOCH + 499
            events.append([sample, 0, task_code])

    elif task_code in STIMULUS_AT_0:
        event_name = f"cue/{task_label}"
        event_id[event_name] = task_code
        for i in range(n_epochs):
            sample = i * SAMPLES_PER_EPOCH
            events.append([sample, 0, task_code])

    events = np.array(events, dtype=int) if events else np.empty((0, 3), dtype=int)
    return events, event_id


# ── BIDS writing ─────────────────────────────────────────────────────────────


def write_dataset_description(bids_root: Path):
    """Write dataset_description.json."""
    desc = {
        "Name": "M3CV: Multi-subject, Multi-session, Multi-task EEG Database",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "CC BY 4.0",
        "Authors": [
            "Gan Huang",
            "Zhenxing Hu",
            "Weize Chen",
            "Shaorong Zhang",
            "Zhen Liang",
            "Linling Li",
            "Li Zhang",
            "Zhiguo Zhang",
        ],
        "Funding": [
            "National Natural Science Foundation of China (62271326, 81871443, 61906122, 81901831)",
            "Shenzhen Municipality Science, Technology and Innovation Commission (JCYJ20190908181739182)",
            "Shenzhen Science and Technology Program (JSGG20210713091811038)",
            "Shenzhen Hong Kong Institute of Brain Science-Shenzhen Fundamental Research Institutions (2022SHIBS0003)",
            "Shenzhen Sanming Project of Medicine (SZSM202111009)",
            "Shenzhen Special Project for Sustainable Development (KCXFZ20201221173400001)",
        ],
        "EthicsApprovals": [
            "Medical Ethics Committee, Health Science Center, Shenzhen University (No. 2019053)",
        ],
        "DatasetDOI": "doi:10.1016/j.neuroimage.2022.119666",
        "ReferencesAndLinks": [
            "https://doi.org/10.1016/j.neuroimage.2022.119666",
            "https://www.kaggle.com/competitions/eeg-based-biometric-competition",
            "https://www.kaggle.com/competitions/eeg-biometric-competition",
        ],
        "HowToAcknowledge": (
            "Please cite: Huang, G. et al. (2022). M3CV: A multi-subject, "
            "multi-session, and multi-task database for EEG-based biometrics "
            "challenge. NeuroImage, 264, 119666."
        ),
        "SourceDatasets": [
            {
                "URL": "https://www.kaggle.com/competitions/eeg-based-biometric-competition",
                "Version": "2022-07-27",
            }
        ],
        "GeneratedBy": [
            {
                "Name": "convert_m3cv.py (EEGDash)",
                "Description": (
                    "Reconstructed pseudo-continuous EEG from pre-epoched .mat "
                    "files distributed via Kaggle. Epochs concatenated per "
                    "subject/session/task. Original continuous recordings are "
                    "not publicly available."
                ),
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    """Write README."""
    readme = """\
M3CV: Multi-subject, Multi-session, and Multi-task EEG Database
================================================================

Overview
--------
This dataset contains 64-channel EEG from 95 healthy young adults (Age:
21.3 +/- 2.2 years; 73 males, 22 females) from Shenzhen University, recorded
across 2 sessions on different days using a BrainAmp amplifier with 64-channel
Easycap (standard 10-20 positions). Each subject performed 6 paradigms with 14
types of EEG signals across 15 runs per session (~50 min recording, ~2 h total
including setup and rest). The original paper describes 14 signal types; the
distributed data contains 13 task codes because nontarget P300 epochs were not
included.

The original data was recorded at 1000 Hz and preprocessed using Matlab 2018b
with Letswave7 (letswave.cn), then distributed as individual 4-second epoched
.mat files at 250 Hz.

This BIDS version reconstructs pseudo-continuous EEG by concatenating the
distributed epochs per subject/session/task. Event markers indicate epoch
boundaries and stimulus onsets derived from the original marker channel.

Ethics: Medical Ethics Committee, Health Science Center, Shenzhen University
(No. 2019053). All subjects gave informed consent.

Recording Setup
---------------
- Amplifier: BrainAmp (Brain Products GmbH, Germany)
- Cap: 64-channel Easycap, standard 10-20 positions
- Online reference: FCz; Ground: AFz
- Sampling rate: 1000 Hz (distributed at 250 Hz after preprocessing)
- Impedance: < 20 kOhm
- Subject distance: ~1 meter from screen
- Screen: 24.5-inch Alienware AW2518H (1920x1080, 240 Hz refresh rate)
- Visual stimuli: Psychtoolbox-3 in Matlab
- Sensory stimuli: Arduino Uno platform via serial port to Matlab
- LED: 3 W, 2 cm diameter circular shield, 45 cm from eyes, 1074 Lux
  (measured by TES-1332A light meter)
- Headphones: Nokia WH-102, 75 dB SPL average
- Vibration motor: 1027 disk, 3 W rated, 80% efficiency, 10 mm x 2.7 mm,
  placed on subject's left hand
- Power line frequency: 50 Hz

Preprocessing (applied before distribution, Table 3 of paper)
--------------------------------------------------------------
Software: Matlab 2018b & Letswave7 (letswave.cn)
1. Bad channels identified manually, interpolated with mean of 3 surrounding
   channels (22 of 95 subjects had bad channels)
2. Channel FCz (online reference) added back
3. Channel IO (EOG) removed
4. Bandpass filter: 0.01-200 Hz, 4th-order Butterworth, 24 dB/octave, zero-phase
5. Notch filter: 49-51 Hz bandstop, 4th-order Butterworth, 24 dB/octave, zero-phase
6. Re-referenced to mean of TP9 and TP10 (linked mastoids)
7. ICA artifact removal: eye blink and eye movement components identified by
   visual inspection of scalp topographies, time courses, and spectra
   (Huang et al., 2020)
8. Downsampled to 250 Hz
9. No bad epoch rejection (intentional for ML robustness/repeatability)

Note: One subject was removed due to strong 10 Hz artifacts. The remaining 95
subjects are included in the distributed data.

Paradigms (14 signal types, 13 in distributed data, 15 runs/session)
---------------------------------------------------------------------
Run 01: Eyes Closed resting (restEC) — 1 min; fixate on LED (off)
Run 02: Eyes Open resting (restEO) — 1 min; fixate ahead, minimal blink
Run 03: Motor execution (motorFoot/motorRHand/motorLHand) — 20 trials each
Run 04: Transient sensory (vep/aep/sep) — 30 trials each, random order, ~4.5 min
Run 05: SSVEP (ssvep) — 10 Hz LED, 1 min
Run 06: Motor execution — 20 trials each
Run 07: P300 oddball (p300) — 600 stimuli (5% target=30, nontarget=570), 80 ms,
        ISI 200 ms, 2 min; red/white 300x300 px squares; subjects count red
Run 08: SSVEP-SA (ssvepSA) — 6 freq (7/8/9/11/13/15 Hz), 12 segments x 10 s
Run 09: SSAEP (ssaep) — 45.38 Hz, 2 min
Run 10: Motor execution — 20 trials each
Run 11: Transient sensory — 30 trials each, random order
Run 12: SSSEP (sssep) — 22.04 Hz vibration, 2 min
Run 13: Motor execution — 20 trials each
Run 14: Eyes Closed resting (restEC) — 1 min
Run 15: Eyes Open resting (restEO) — 1 min

Motor execution details: subjects gripped (LH/RH) or lifted ankle (FT) at
~2x/sec, ~80% maximum voluntary contraction, 3 s duration until cue offset.
No feedback, metronome, or hint was provided. Experimenters monitored movement
quality during recording.

Notes on distributed data
--------------------------
- 14 signal types in the paper, 13 task codes in distributed data:
  nontarget P300 (paper task 10, trigger S10) was not distributed
- P300: Only 30 target trials stored per subject; 570 nontarget discarded
- SSVEP-SA: 6 frequency classes not distinguishable in marker; all marker=13
- Trigger codes in original recording (S1-S25) differ from CSV Task column
  (1-13). CSV Task 10=FT, 11=RH, 12=LH (paper tasks 11-13, triggers S6-S8)
- Epoch ordering within task may not reflect original temporal sequence
- 11 "intruder" subjects in Testing set have hidden SubjectIDs (excluded here)

Subjects and Sessions
---------------------
- 106 total subjects; 95 completed both sessions
- Age: 21.3 +/- 2.2 years (95 subjects); 73 males, 22 females
- Normal hearing, normal/corrected vision, no neurological history (self-report)
- Between-session interval: 6 to 139 days (mean ~20 days)
- ses-01 = session 1 (Enrollment set)
- ses-02 = session 2 (Calibration + Testing sets)
- 11 "intruder" subjects (session 2 only, hidden IDs) are excluded from BIDS

Competition context
-------------------
Originally distributed for the M3CV EEG-based Biometric Competition on Kaggle
(identification and verification tasks). Competition closed Apr 30, 2023; late
submissions remain allowed.

Reference
---------
Huang, G., Hu, Z., Chen, W., Zhang, S., Liang, Z., Li, L., Zhang, L., &
Zhang, Z. (2022). M3CV: A multi-subject, multi-session, and multi-task
database for EEG-based biometrics challenge. NeuroImage, 264, 119666.
https://doi.org/10.1016/j.neuroimage.2022.119666
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def write_participants(bids_root: Path, metadata: pd.DataFrame):
    """Write participants.tsv and participants.json."""
    known = metadata.dropna(subset=["SubjectID"])
    subjects = sorted(known["SubjectID"].unique())

    rows = []
    for sub_id in subjects:
        sub_num = sub_id.replace("sub", "")
        sub_data = known[known["SubjectID"] == sub_id]
        n_sessions = sub_data["Session"].nunique()
        n_epochs_total = len(sub_data)
        tasks_available = sorted(sub_data["Task"].unique())
        sets_in = sorted(sub_data["Set"].unique())

        rows.append(
            {
                "participant_id": f"sub-{sub_num}",
                "age": "n/a",
                "sex": "n/a",
                "handedness": "n/a",
                "group": "control",
                "n_sessions": n_sessions,
                "n_epochs_total": n_epochs_total,
                "n_tasks": len(tasks_available),
                "in_enrollment": "yes" if "Enrollment" in sets_in else "no",
                "in_calibration": "yes" if "Calibration" in sets_in else "no",
                "in_testing": "yes" if "Testing" in sets_in else "no",
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(bids_root / "participants.tsv", sep="\t", index=False)

    desc = {
        "participant_id": {"Description": "Unique participant identifier"},
        "age": {
            "Description": "Age at time of recording (not available per-subject; group mean 21.3 +/- 2.2 years)",
            "Units": "years",
        },
        "sex": {
            "Description": "Biological sex (not available per-subject; group: 73 males / 22 females of 95)",
            "Levels": {"M": "male", "F": "female"},
        },
        "handedness": {
            "Description": "Dominant hand (not reported in original study)",
            "Levels": {"R": "right", "L": "left", "A": "ambidextrous"},
        },
        "group": {
            "Description": "Subject group",
            "Levels": {"control": "Healthy young adult from Shenzhen University"},
        },
        "n_sessions": {
            "Description": "Number of recording sessions (2 for all 95 subjects)"
        },
        "n_epochs_total": {
            "Description": "Total number of epochs across all sessions, tasks, and competition sets",
        },
        "n_tasks": {
            "Description": "Number of distinct task types available for this subject"
        },
        "in_enrollment": {
            "Description": "Whether subject appears in the Enrollment set (session 1, training data)",
            "Levels": {"yes": "Present in Enrollment", "no": "Not in Enrollment"},
        },
        "in_calibration": {
            "Description": "Whether subject appears in the Calibration set (session 2, 20 subjects for tuning)",
            "Levels": {"yes": "Present in Calibration", "no": "Not in Calibration"},
        },
        "in_testing": {
            "Description": "Whether subject appears in the Testing set (session 2, evaluation)",
            "Levels": {"yes": "Present in Testing", "no": "Not in Testing"},
        },
    }
    with open(bids_root / "participants.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_enriched_events_tsv(
    bids_path: mne_bids.BIDSPath,
    epochs_df: pd.DataFrame,
    epoch_ids: list[str],
    task_code: int,
):
    """Overwrite the events.tsv with richer metadata columns."""
    task_label, task_desc, paradigm, stim_desc = TASK_MAP[task_code]
    events_path = bids_path.copy().update(suffix="events", extension=".tsv")
    fpath = events_path.fpath
    if not fpath.exists():
        return

    ev = pd.read_csv(fpath, sep="\t")

    # Add enriched columns
    if len(epoch_ids) != len(ev):
        logger.warning(
            "Epoch ID count (%d) != event count (%d) for task %d — truncating",
            len(epoch_ids),
            len(ev),
            task_code,
        )
    ev["epoch_index"] = range(len(ev))
    ev["epoch_id"] = (
        epoch_ids[: len(ev)]
        if len(epoch_ids) >= len(ev)
        else epoch_ids + ["n/a"] * (len(ev) - len(epoch_ids))
    )
    ev["task_code"] = task_code
    ev["paradigm"] = paradigm
    ev["stimulus_description"] = stim_desc

    if task_code in CONTINUOUS_TASKS:
        ev["duration"] = EPOCH_DURATION_S
    elif task_code in STIMULUS_AT_499:
        ev["duration"] = 0.05  # 50ms stimulus for VEP/AEP/SEP, 80ms for P300
        if task_code == 9:
            ev["duration"] = 0.08
    elif task_code in STIMULUS_AT_0:
        ev["duration"] = 3.0  # 3s movement duration until cue offset

    ev.to_csv(fpath, sep="\t", index=False)

    # Write events.json sidecar
    events_json = {
        "sample": {
            "Description": "Onset sample index (0-based) in the continuous recording",
        },
        "StimulusPresentation": {
            "SoftwareName": "Psychtoolbox-3",
            "SoftwareVersion": "3.x (in Matlab 2018b)",
            "ScreenDistance": 100,
            "ScreenRefreshRate": 240,
            "ScreenResolution": [1920, 1080],
        },
        "trial_type": {
            "Description": "Type of event",
            "Levels": {ev["trial_type"].iloc[0]: task_desc},
        },
        "value": {"Description": "Event code from the M3CV marker channel"},
        "epoch_index": {
            "Description": "Sequential epoch index within this task (0-based)"
        },
        "epoch_id": {"Description": "Original EpochID from M3CV dataset CSV files"},
        "task_code": {
            "Description": "Original M3CV task code (1-13)",
            "Levels": {
                str(k): v[1].split(" — ")[0] if " — " in v[1] else v[1]
                for k, v in TASK_MAP.items()
            },
        },
        "paradigm": {
            "Description": "Experimental paradigm grouping",
            "Levels": PARADIGM_NAMES,
        },
        "stimulus_description": {
            "Description": "Physical stimulus parameters from the original paper",
        },
    }
    json_path = bids_path.copy().update(suffix="events", extension=".json")
    with open(json_path.fpath, "w") as f:
        json.dump(events_json, f, indent=2)
        f.write("\n")


def write_scans_tsv(
    bids_root: Path, subject: str, session: str, task_files: list[dict]
):
    """Write a scans.tsv file listing all EEG files for a subject/session."""
    scans_dir = bids_root / f"sub-{subject}" / f"ses-{session}"
    scans_path = scans_dir / f"sub-{subject}_ses-{session}_scans.tsv"

    rows = []
    for tf in task_files:
        rows.append(
            {
                "filename": f"eeg/{tf['filename']}",
                "acq_time": "n/a",
                "n_epochs": tf["n_epochs"],
                "duration_s": tf["n_epochs"] * EPOCH_DURATION_S,
                "task_code": tf["task_code"],
                "paradigm": tf["paradigm"],
            }
        )

    df = pd.DataFrame(rows)
    scans_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(scans_path, sep="\t", index=False)

    # Write scans.json sidecar for non-standard columns
    scans_json_path = scans_dir / f"sub-{subject}_ses-{session}_scans.json"
    scans_desc = {
        "filename": {
            "Description": "Path to EEG file relative to subject/session directory"
        },
        "acq_time": {
            "Description": "Acquisition time (not available for this dataset)"
        },
        "n_epochs": {"Description": "Number of concatenated 4-second epochs"},
        "duration_s": {"Description": "Total duration in seconds", "Units": "s"},
        "task_code": {"Description": "Original M3CV task code (1-13)"},
        "paradigm": {"Description": "Experimental paradigm grouping"},
    }
    with open(scans_json_path, "w") as f:
        json.dump(scans_desc, f, indent=2)
        f.write("\n")


def convert_subject_session_task(
    metadata: pd.DataFrame,
    input_dir: Path,
    bids_root: Path,
    subject_id: str,
    session: int,
    task_code: int,
    *,
    overwrite: bool = True,
    verbose: bool = False,
) -> dict | None:
    """Convert one subject/session/task to BIDS.

    Returns file info dict if successful, None if skipped.
    """
    task_label, task_desc, paradigm, stim_desc = TASK_MAP[task_code]
    sub_num = subject_id.replace("sub", "")
    ses_label = f"{session:02d}"

    # Filter metadata
    mask = (
        (metadata["SubjectID"] == subject_id)
        & (metadata["Session"] == session)
        & (metadata["Task"] == task_code)
    )
    epochs_df = metadata[mask].sort_values("EpochID")

    if len(epochs_df) == 0:
        return None

    # Validate epoch count against expected
    expected = EXPECTED_EPOCHS.get(task_code)
    actual = len(epochs_df)
    if expected and abs(actual - expected) > 2:
        logger.warning(
            "sub-%s ses-%s task-%s: %d epochs (expected ~%d)",
            sub_num,
            ses_label,
            task_label,
            actual,
            expected,
        )

    # Build concatenated Raw + events (handles mixed Sets per epoch)
    raw, events, event_id, epoch_ids = build_concatenated_raw(epochs_df, input_dir)

    # Create BIDS path
    bids_path = mne_bids.BIDSPath(
        subject=sub_num,
        session=ses_label,
        task=task_label,
        datatype="eeg",
        root=bids_root,
    )

    # Write to BIDS
    write_kwargs = dict(
        raw=raw,
        bids_path=bids_path,
        overwrite=overwrite,
        verbose=verbose,
        allow_preload=True,
        format="BrainVision",
    )
    if len(events) > 0:
        write_kwargs["events"] = events
        write_kwargs["event_id"] = event_id
    mne_bids.write_raw_bids(**write_kwargs)

    # Use actual loaded epoch count (may differ from metadata if files were skipped)
    actual_n_epochs = len(epoch_ids)

    # Enrich the sidecar JSON with M3CV-specific metadata
    _update_sidecar(bids_path, task_code, actual_n_epochs)

    # Update coordsystem.json with fiducials and description
    _update_coordsystem(bids_path)

    # Overwrite events.tsv with enriched version
    write_enriched_events_tsv(bids_path, epochs_df, epoch_ids, task_code)

    logger.info(
        "Converted sub-%s ses-%s task-%s: %d epochs (%.1fs)",
        sub_num,
        ses_label,
        task_label,
        actual_n_epochs,
        actual_n_epochs * EPOCH_DURATION_S,
    )

    return {
        "filename": f"sub-{sub_num}_ses-{ses_label}_task-{task_label}_eeg.vhdr",
        "n_epochs": actual_n_epochs,
        "task_code": task_code,
        "paradigm": paradigm,
    }


def _update_coordsystem(bids_path: mne_bids.BIDSPath):
    """Add fiducials and description to coordsystem.json."""
    coord_path = bids_path.copy().update(
        suffix="coordsystem",
        extension=".json",
        space="CapTrak",
        task=None,
    )
    fpath = coord_path.fpath
    if not fpath.exists():
        return

    with open(fpath) as f:
        coord = json.load(f)

    coord.update(
        {
            "FiducialsCoordinates": {
                "NAS": coord.get("AnatomicalLandmarkCoordinates", {}).get("NAS", "n/a"),
                "LPA": coord.get("AnatomicalLandmarkCoordinates", {}).get("LPA", "n/a"),
                "RPA": coord.get("AnatomicalLandmarkCoordinates", {}).get("RPA", "n/a"),
            },
            "FiducialsCoordinateSystem": "CapTrak",
            "FiducialsCoordinateUnits": "m",
            "FiducialsCoordinateSystemDescription": (
                "Based on the standard_1005 montage from MNE-Python. "
                "Fiducial positions are derived from the template, not "
                "individually digitized."
            ),
            "AnatomicalLandmarkCoordinateSystemDescription": (
                "Based on the standard_1005 montage from MNE-Python. "
                "NAS=nasion, LPA=left preauricular, RPA=right preauricular."
            ),
        }
    )

    with open(fpath, "w") as f:
        json.dump(coord, f, indent=2)
        f.write("\n")


def _update_sidecar(bids_path: mne_bids.BIDSPath, task_code: int, n_epochs: int):
    """Add M3CV-specific metadata to the EEG sidecar JSON."""
    sidecar_path = bids_path.copy().update(suffix="eeg", extension=".json")
    fpath = sidecar_path.fpath
    if not fpath.exists():
        return

    task_label, task_desc, paradigm, stim_desc = TASK_MAP[int(task_code)]
    task_code = int(task_code)
    n_epochs = int(n_epochs)

    with open(fpath) as f:
        sidecar = json.load(f)

    sidecar.update(
        {
            "TaskName": task_label,
            "TaskDescription": task_desc,
            "InstitutionName": "Shenzhen University",
            "InstitutionalDepartmentName": "School of Biomedical Engineering, Health Science Center",
            "InstitutionAddress": "Shenzhen, Guangdong 518060, China",
            "Manufacturer": "Brain Products GmbH",
            "ManufacturersModelName": "BrainAmp",
            "CapManufacturer": "Easycap",
            "CapManufacturersModelName": "64-channel Easycap",
            "EEGReference": "TP9/TP10 (linked mastoids, applied offline during preprocessing)",
            "EEGGround": "AFz",
            "EEGPlacementScheme": "10-20",
            "PowerLineFrequency": 50,
            "StimulusPresentation": {
                "SoftwareName": "Psychtoolbox-3",
                "SoftwareVersion": "3.x (in Matlab 2018b)",
                "ScreenDistance": 100,
                "ScreenRefreshRate": 240,
                "ScreenResolution": [1920, 1080],
                "ScreenSize": 24.5,
                "AdditionalHardware": "Arduino Uno for sensory stimuli via serial port; "
                "Nokia WH-102 headphones; 3W LED with TES-1332A light meter; "
                "1027 disk vibration motor",
            },
            "SoftwareFilters": {
                "BandpassFilter": {
                    "lowFreq": 0.01,
                    "highFreq": 200,
                    "order": 4,
                    "rolloff": "24 dB/octave",
                    "type": "Butterworth",
                    "phase": "zero-phase",
                },
                "NotchFilter": {
                    "lowFreq": 49,
                    "highFreq": 51,
                    "order": 4,
                    "rolloff": "24 dB/octave",
                    "type": "Butterworth",
                    "phase": "zero-phase",
                },
            },
            "HardwareFilters": "n/a",
            "SoftwareVersions": "n/a",
            "DeviceSerialNumber": "n/a",
            "CogAtlasID": "n/a",
            "CogPOID": "n/a",
            "MISCChannelCount": 0,
            "PreprocessingSoftware": "Matlab 2018b with Letswave7 (letswave.cn)",
            "SubjectArtefactDescription": (
                "Bad channels identified manually and interpolated with the mean "
                "of three surrounding channels (22 subjects had bad channels). "
                "Eye blink and eye movement artifacts removed by ICA — components "
                "identified by visual inspection of scalp topographies, time "
                "courses, and spectra (Huang et al., 2020). No bad epoch rejection."
            ),
            "RecordingType": "continuous",
            "EpochLength": EPOCH_DURATION_S,
            "NumberOfEpochs": n_epochs,
            "SourceSamplingFrequency": 1000,
            "OriginalTaskCode": task_code,
            "Paradigm": paradigm,
            "StimulusDescription": stim_desc,
            "Note": (
                "This file contains pseudo-continuous EEG reconstructed by "
                "concatenating pre-epoched 4-second segments from the M3CV "
                "competition dataset. The original continuous BrainVision "
                "recordings are not publicly available. Data was preprocessed "
                "(filtered, ICA-cleaned, re-referenced, downsampled) before "
                "distribution."
            ),
        }
    )

    # Task-specific instructions
    instructions_map = {
        1: "Keep eyes closed and fixate on the LED (off state).",
        2: "Keep eyes open, fixate straight ahead, and blink as little as possible.",
        3: "Remain still. Visual, auditory, and somatosensory stimuli will be presented in random order.",
        4: "Remain still. Visual, auditory, and somatosensory stimuli will be presented in random order.",
        5: "Remain still. Visual, auditory, and somatosensory stimuli will be presented in random order.",
        6: "Fixate on the LED while it flickers.",
        7: "Listen to the auditory stimulation through headphones.",
        8: "Remain still while the vibration motor stimulates your left hand.",
        9: "Count the number of red squares and report the count after the run.",
        10: "When the visual cue appears, lift your right ankle at ~2x/sec, ~80% effort, for 3 seconds.",
        11: "When the visual cue appears, grip your right hand at ~2x/sec, ~80% effort, for 3 seconds.",
        12: "When the visual cue appears, grip your left hand at ~2x/sec, ~80% effort, for 3 seconds.",
        13: "Focus on the target square (briefly shown in red) during the 10-second flicker period. "
        "Maintain fixation at center of screen.",
    }
    if task_code in instructions_map:
        sidecar["Instructions"] = instructions_map[task_code]

    # Original trigger code mapping (Table 2 of paper)
    original_triggers = {
        1: "S 1",
        2: "S 2",
        3: "S 3",
        4: "S 4",
        5: "S 5",
        6: "S 23",
        7: "S 24",
        8: "S 25",
        9: "S 9 (target); S 10 was nontarget (not distributed)",
        10: "S 6",
        11: "S 7",
        12: "S 8",
        13: "S 11-S 16 (cue per freq), S 17-S 22 (stim onset per freq)",
    }
    if task_code in original_triggers:
        sidecar["OriginalTriggerCode"] = original_triggers[task_code]

    # Task-specific additions
    if task_code == 9:
        sidecar["P300Note"] = (
            "Only target trials (30 per session) are included. The 570 "
            "nontarget trials per session were discarded before distribution."
        )
    if task_code == 13:
        sidecar["SSVEPSANote"] = (
            "Six frequency classes (7, 8, 9, 11, 13, 15 Hz) were used but "
            "the frequency class label is NOT encoded in the marker channel. "
            "All epochs have marker=13."
        )
    if task_code in EXPECTED_EPOCHS:
        sidecar["ExpectedEpochCount"] = EXPECTED_EPOCHS[task_code]

    with open(fpath, "w") as f:
        json.dump(sidecar, f, indent=2)
        f.write("\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def convert_m3cv(
    input_dir: Path,
    output_dir: Path,
    subjects: list[str] | None = None,
    sessions: list[int] | None = None,
    tasks: list[int] | None = None,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
):
    """Run the full M3CV → BIDS conversion."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = load_metadata(input_dir)
    # Filter out intruder subjects (NaN, empty string, or "None" SubjectID)
    known = metadata.copy()
    known = known[known["SubjectID"].notna()]
    known = known[known["SubjectID"].astype(str).str.strip() != ""]
    known = known[known["SubjectID"].astype(str) != "None"]
    n_intruder = len(metadata) - len(known)
    if n_intruder > 0:
        logger.info("Filtered out %d intruder epochs (hidden SubjectID)", n_intruder)

    all_subjects = sorted(known["SubjectID"].unique())
    if subjects is not None:
        all_subjects = [s for s in all_subjects if s in subjects]
        if not all_subjects:
            available = sorted(known["SubjectID"].unique())[:5]
            raise ValueError(
                f"No subjects matched filter {subjects}. "
                f"Available IDs look like: {available}..."
            )
    logger.info("Converting %d subjects", len(all_subjects))

    all_sessions = sorted(known["Session"].unique())
    if sessions is not None:
        all_sessions = [s for s in all_sessions if s in sessions]

    all_tasks = sorted(known["Task"].unique())
    if tasks is not None:
        all_tasks = [t for t in all_tasks if t in tasks]

    if dry_run:
        for sub in all_subjects:
            for ses in all_sessions:
                for task in all_tasks:
                    mask = (
                        (known["SubjectID"] == sub)
                        & (known["Session"] == ses)
                        & (known["Task"] == task)
                    )
                    n = mask.sum()
                    if n > 0:
                        task_label = TASK_MAP[task][0]
                        sub_num = sub.replace("sub", "")
                        print(
                            f"  sub-{sub_num}/ses-{ses:02d}/task-{task_label}: "
                            f"{n} epochs ({n * EPOCH_DURATION_S:.0f}s)"
                        )
        return

    # Write top-level BIDS files
    write_dataset_description(output_dir)
    write_readme(output_dir)
    write_participants(output_dir, known)

    # Convert each subject/session/task
    n_converted = 0
    for si, sub in enumerate(all_subjects):
        for ses in all_sessions:
            task_files = []
            for task in all_tasks:
                result = convert_subject_session_task(
                    known,
                    input_dir,
                    output_dir,
                    sub,
                    ses,
                    task,
                    overwrite=overwrite,
                    verbose=verbose,
                )
                if result is not None:
                    n_converted += 1
                    task_files.append(result)

            # Write scans.tsv per subject/session
            if task_files:
                sub_num = sub.replace("sub", "")
                write_scans_tsv(output_dir, sub_num, f"{ses:02d}", task_files)

        pct = (si + 1) / len(all_subjects) * 100
        logger.info("Progress: %d/%d subjects (%.0f%%)", si + 1, len(all_subjects), pct)

    logger.info("Done: %d files converted", n_converted)


def main():
    parser = argparse.ArgumentParser(
        description="Convert M3CV dataset to BIDS-EEG format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="Path to extracted M3CV data (contains Enrollment/, Calibration/, *.csv)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Output BIDS directory",
    )
    parser.add_argument(
        "--subjects",
        "-s",
        nargs="+",
        default=None,
        help="Subject IDs to convert (e.g., sub001 sub002). Default: all.",
    )
    parser.add_argument(
        "--sessions",
        nargs="+",
        type=int,
        default=None,
        help="Sessions to convert (1, 2, or both). Default: all.",
    )
    parser.add_argument(
        "--tasks",
        "-t",
        nargs="+",
        type=int,
        default=None,
        help="Task codes to convert (1-13). Default: all.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Do not overwrite existing BIDS files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be converted without writing files.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output from MNE.",
    )
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

    if not args.verbose:
        mne.set_log_level("WARNING")

    convert_m3cv(
        input_dir=args.input,
        output_dir=args.output,
        subjects=args.subjects,
        sessions=args.sessions,
        tasks=args.tasks,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
