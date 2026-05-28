#!/usr/bin/env python3
from __future__ import annotations

"""Convert the VocalMind sEEG dataset to BIDS-iEEG format.

VocalMind is a stereotactic EEG (sEEG) dataset of speech production from a
single epilepsy patient (22-year-old male, native Mandarin speaker) recorded
at 1000 Hz with a Nihon Kohden EEG-1200 system. 9 electrode shafts ×
12-16 contacts = 140 total electrodes (110 after excluding 30 abnormal).

Three speech modes:
  - Vocalized: reading words/sentences aloud
  - Mimed: silent lip movement (no voice)
  - Imagined: internal speech (no movement)

Two task types:
  - Word: 20 Mandarin words covering all 4 tones, each repeated multiple times
  - Sentence: 100 sentences (5-8 characters) from WenetSpeech corpus

The Zenodo release ships BOTH raw and preprocessed data:
  - Original_sEEG: raw 1000 Hz, unfiltered (only bad electrodes removed)
  - Processed_sEEG: HGA (70-150 Hz) + LFS (<100 Hz) at 200 Hz
  - Original_Audio: WAV recordings of speech
  - Processed_Audio: mel spectrograms

This converter uses the **Original_sEEG** (raw 1000 Hz) as the primary data
and places the processed features in /derivatives/.

Reference:
    He, T., Wei, M., Wang, R., Wang, R., Du, S., Cai, S., Tao, W. & Li, H.
    (2025). VocalMind: A Stereotactic EEG Dataset for Vocalized, Mimed, and
    Imagined Speech in Tonal Language. Scientific Data, 12, 703.
    https://doi.org/10.1038/s41597-025-04741-2

Ethics: South China Hospital, Shenzhen University (HNLS20231229003-A)

Usage:
    python convert_vocalmind.py --input /tmp/vocalmind --output /tmp/vocalmind_bids
    python convert_vocalmind.py --input /tmp/vocalmind --output /tmp/vocalmind_bids --dry-run
"""

import argparse
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

import mne
import mne_bids
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SFREQ = 1000.0  # Original sEEG sampling rate (Hz)
N_ELECTRODES_TOTAL = 140  # Before exclusion of abnormal channels
N_ELECTRODES_CLEAN = 110  # After excluding 30 abnormal channels

# Speech modes → BIDS task entity
SPEECH_MODES = {
    "Vocalized": "vocalized",
    "Mimed": "mimed",
    "Imagined": "imagined",
}

# Task types → BIDS acquisition entity
TASK_TYPES = {
    "Word": "word",
    "Sentence": "sentence",
}

DATASET_DESCRIPTION = {
    "Name": (
        "He et al. 2025 — VocalMind: A Stereotactic EEG Dataset for "
        "Vocalized, Mimed, and Imagined Speech in Tonal Language"
    ),
    "BIDSVersion": "1.9.0",
    "HEDVersion": "8.2.0",
    "DatasetType": "raw",
    "License": "CC BY 4.0",
    "Authors": [
        "Tianyu He",
        "Mingyi Wei",
        "Ruicong Wang",
        "Renzhi Wang",
        "Shiwei Du",
        "Siqi Cai",
        "Wei Tao",
        "Haizhou Li",
    ],
    "DatasetDOI": "doi:10.1038/s41597-025-04741-2",
    "EthicsApprovals": [
        "Ethics Committee of South China Hospital, Shenzhen University (HNLS20231229003-A)"
    ],
    "ReferencesAndLinks": [
        "https://doi.org/10.1038/s41597-025-04741-2",
        "https://zenodo.org/records/14696348",
        "https://tianyu-h42.github.io/sEEG_speechDecoding/",
    ],
    "HowToAcknowledge": (
        "Please cite: He, T. et al. (2025). VocalMind: A Stereotactic EEG "
        "Dataset for Vocalized, Mimed, and Imagined Speech in Tonal Language. "
        "Scientific Data, 12, 703. https://doi.org/10.1038/s41597-025-04741-2"
    ),
    "SourceDatasets": [
        {
            "URL": "https://zenodo.org/records/14696348",
            "DOI": "doi:10.5281/zenodo.14696348",
        }
    ],
    "GeneratedBy": [
        {
            "Name": "convert_vocalmind.py (EEGDash)",
            "Description": (
                "Converted Original_sEEG CSV files (raw 1000 Hz) to "
                "BIDS-iEEG BrainVision format. Per-trial CSV files are "
                "concatenated per speech-mode/task-type with events.tsv "
                "marking each stimulus onset."
            ),
            "CodeURL": "https://github.com/bruaristimunha/EEGDash",
        }
    ],
    "Funding": [
        "National Natural Science Foundation of China",
        "Shenzhen Science and Technology Innovation Program",
    ],
    "Version": "1.0.0",
}


def extract_all_zips(input_dir: Path) -> Path:
    """Extract all zip files to input_dir/extracted/."""
    extract_dir = input_dir / "extracted"
    extract_dir.mkdir(exist_ok=True)
    for zf_path in sorted(input_dir.glob("*.zip")):
        target = extract_dir / zf_path.stem
        if target.exists():
            continue
        logger.info("Extracting %s...", zf_path.name)
        try:
            with zipfile.ZipFile(zf_path) as zf:
                zf.extractall(extract_dir)
        except Exception as exc:
            logger.warning("Failed to extract %s: %s", zf_path.name, exc)
    return extract_dir


def find_original_seeg_dirs(extract_dir: Path) -> list[Path]:
    """Find all Original_sEEG_* directories."""
    return sorted(
        d
        for d in extract_dir.iterdir()
        if d.is_dir() and d.name.startswith("Original_sEEG_")
    )


def parse_dir_name(dir_name: str) -> tuple[str, str] | None:
    """Parse 'Original_sEEG_Vocalized_Word' → ('vocalized', 'word')."""
    m = re.match(r"Original_sEEG_(\w+)_(\w+)", dir_name)
    if not m:
        return None
    mode = SPEECH_MODES.get(m.group(1))
    task_type = TASK_TYPES.get(m.group(2))
    if not mode or not task_type:
        return None
    return mode, task_type


def load_and_concatenate_trials(
    seeg_dir: Path,
) -> tuple[np.ndarray, list[dict], list[str]]:
    """Load all CSV trial files, concatenate, and build events list.

    Each CSV file is a single trial with:
      - Row 0: electrode IDs (integers 9-145, with gaps for excluded channels)
      - Rows 1-N: time samples × channels. Data is in VOLTS.

    Returns (data_array, events_list, ch_names) where data_array is
    (n_channels, n_times) in MNE convention.
    """
    csv_files = sorted(seeg_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files in {seeg_dir}")

    # Read electrode IDs from the first file's first row
    first_df = pd.read_csv(csv_files[0], header=None, nrows=1)
    electrode_ids = first_df.iloc[0].values.astype(int)
    ch_names = [f"sEEG{eid:03d}" for eid in electrode_ids]

    arrays = []
    events = []
    onset_sample = 0

    for csv_path in csv_files:
        # Row 0 = electrode IDs (skip), rows 1+ = (n_times, n_channels) in volts
        trial_data = pd.read_csv(csv_path, header=None, skiprows=1).values
        n_times, n_ch = trial_data.shape

        # Parse trial label from filename: e.g. "Vocalized_DaNao_1.csv"
        label = csv_path.stem

        events.append(
            {
                "onset": onset_sample / SFREQ,
                "duration": n_times / SFREQ,
                "trial_type": label,
            }
        )
        arrays.append(trial_data)
        onset_sample += n_times

    # Concatenate along time axis: (total_times, n_ch) → transpose to (n_ch, total_times)
    concat = np.concatenate(arrays, axis=0).T  # (n_ch, total_times) — MNE convention
    return concat, events, ch_names


def convert_vocalmind(
    input_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write dataset_description.json
    with open(output_dir / "dataset_description.json", "w") as f:
        json.dump(DATASET_DESCRIPTION, f, indent=2)
        f.write("\n")

    # Extract all zips
    extract_dir = extract_all_zips(input_dir)

    if dry_run:
        for d in find_original_seeg_dirs(extract_dir):
            parsed = parse_dir_name(d.name)
            if parsed:
                mode, task_type = parsed
                n_csv = len(list(d.glob("*.csv")))
                logger.info(
                    "[DRY] %s → task-%s_acq-%s (%d trials)",
                    d.name,
                    mode,
                    task_type,
                    n_csv,
                )
        return

    # Process each Original_sEEG combination
    seeg_dirs = find_original_seeg_dirs(extract_dir)
    logger.info("Found %d Original_sEEG directories", len(seeg_dirs))

    n_ok = 0
    n_fail = 0
    for seeg_dir in seeg_dirs:
        parsed = parse_dir_name(seeg_dir.name)
        if not parsed:
            logger.warning("Cannot parse: %s", seeg_dir.name)
            n_fail += 1
            continue

        mode, task_type = parsed

        try:
            data, events, ch_names = load_and_concatenate_trials(seeg_dir)
            n_ch, n_times = data.shape
            ch_types = ["seeg"] * n_ch
            info = mne.create_info(
                ch_names, sfreq=SFREQ, ch_types=ch_types, verbose=False
            )
            raw = mne.io.RawArray(data, info, verbose=False)

            bids_path = mne_bids.BIDSPath(
                subject="01",
                task=mode,
                acquisition=task_type,
                datatype="ieeg",
                root=output_dir,
            )

            mne_bids.write_raw_bids(
                raw,
                bids_path,
                overwrite=overwrite,
                verbose=verbose,
                allow_preload=True,
                format="BrainVision",
            )

            # Write events.tsv
            events_df = pd.DataFrame(events)
            events_path = bids_path.copy().update(suffix="events", extension=".tsv")
            events_df.to_csv(str(events_path.fpath), sep="\t", index=False)

            total_secs = n_times / SFREQ
            logger.info(
                "OK task-%s_acq-%s: %d ch, %d trials, %.1f sec (%.1f min)",
                mode,
                task_type,
                n_ch,
                len(events),
                total_secs,
                total_secs / 60,
            )
            n_ok += 1

        except Exception as exc:
            logger.warning("FAILED %s: %s", seeg_dir.name, exc)
            n_fail += 1

    # Copy audio stimuli to /stimuli/
    stimuli_dir = output_dir / "stimuli"
    for audio_dir in sorted(extract_dir.glob("Original_Audio_*")):
        if audio_dir.is_dir():
            dest = stimuli_dir / audio_dir.name
            if not dest.exists():
                shutil.copytree(audio_dir, dest)
                logger.info("Copied stimuli: %s", audio_dir.name)

    # Self-deposit conversion script
    code_dir = output_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).resolve()
    if script_path.exists():
        shutil.copy2(script_path, code_dir / script_path.name)
        logger.info("Copied %s into code/", script_path.name)

    logger.info(
        "Done: %d ok, %d failed (out of %d combos)", n_ok, n_fail, len(seeg_dirs)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert VocalMind sEEG dataset to BIDS-iEEG",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
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
    convert_vocalmind(
        args.input,
        args.output,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
