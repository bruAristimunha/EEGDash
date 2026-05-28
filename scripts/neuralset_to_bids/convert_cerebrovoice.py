#!/usr/bin/env python3
from __future__ import annotations

"""Convert the CerebroVoice/NeuroVox sEEG dataset to BIDS-iEEG format.

2 epilepsy patients with sEEG electrodes, bilingual speech (Mandarin + English
+ digits). The data is distributed as .npy derivatives on Zenodo.

Usage:
    python convert_cerebrovoice.py --input /tmp/cerebrovoice --output /tmp/cerebrovoice_bids

Reference:
    Zhang, X. et al. (2025). CerebroVoice/NeuroVox. Zenodo.
    https://zenodo.org/records/13332808
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

# Verified from cross-referencing WAV audio duration (1.500 s) with
# SEEG trial shape (300, n_ch): 300 / 1.5 = 200.0 Hz exactly.
SFREQ = 200.0
TRIAL_SAMPLES = 300  # all trials are fixed at 300 samples = 1.5 s


def write_dataset_description(bids_root: Path):
    desc = {
        "Name": "CerebroVoice — Zhang et al. 2024: A Stereotactic EEG Dataset and Benchmark for Bilingual Brain-to-Speech Synthesis and Activity Detection",
        "BIDSVersion": "1.9.0",
        "HEDVersion": "8.2.0",
        "DatasetType": "derivative",
        "License": "CC BY 4.0",
        "Authors": ["Xueyi Zhang"],
        "DatasetDOI": "doi:10.5281/zenodo.13332808",
        "ReferencesAndLinks": [
            "https://zenodo.org/records/13332808",
            "https://openreview.net/forum?id=3sfOGsBh85",
            "https://doi.org/10.1109/O-COCOSDA202257103.2022.9997944",
        ],
        "HowToAcknowledge": (
            "Please cite the Zenodo record (doi:10.5281/zenodo.13332808) "
            "and the OpenReview submission (https://openreview.net/forum?id=3sfOGsBh85)."
        ),
        "SourceDatasets": [
            {
                "URL": "https://zenodo.org/records/13332808",
                "DOI": "doi:10.5281/zenodo.13332808",
            }
        ],
        "GeneratedBy": [
            {
                "Name": "convert_cerebrovoice.py (EEGDash)",
                "Description": (
                    "Converted per-trial NPY derivatives to concatenated "
                    "BIDS-iEEG BrainVision format. Each task/acquisition "
                    "combination has all trials concatenated in order with "
                    "an events.tsv marking word onsets. Feature types (LFS, "
                    "HGA, BBS) are encoded in the BIDS acquisition entity."
                ),
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
        "Version": "1.0.0",
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    readme = """\
CerebroVoice: Bilingual sEEG Speech Dataset
=============================================

Overview
--------
Intracranial EEG (sEEG) recordings from 2 epilepsy patients during bilingual
speech tasks (Mandarin Chinese, English, and digit reading). Recorded at
1000 Hz with Nihon Kohden EEG-1200, depth electrodes (platinum-iridium).

Data distributed as preprocessed NPY derivatives:
- LFS: Low-frequency signal
- HGA: High-gamma activity
- BBS: Broadband signal

Tasks: Chinese reading, English reading, digit reading
Subjects: SUB1 (114 channels post-filtering), SUB2 (158 channels)
Duration: ~73 min (SUB1), ~76 min (SUB2)

Source: Zenodo (doi:10.5281/zenodo.13332808)
License: CC BY 4.0
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def convert_cerebrovoice(
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

    # Extract all zips
    zip_files = sorted(input_dir.glob("*.zip"))
    logger.info("Found %d zip files", len(zip_files))

    for zf in zip_files:
        extract_dir = input_dir / "extracted"
        if not (extract_dir / zf.stem).exists():
            logger.info("Extracting %s...", zf.name)
            try:
                with zipfile.ZipFile(zf) as z:
                    z.extractall(extract_dir)
            except Exception as e:
                logger.warning("Failed to extract %s: %s", zf.name, e)

    if dry_run:
        for zf in zip_files:
            print(f"  {zf.name}")
        return

    write_dataset_description(output_dir)
    write_readme(output_dir)

    # Process each subject/task/feature combination by concatenating trials.
    # Each NPY file is one speech utterance: shape (n_times, n_channels).
    # We group by (subject, feature, task), sort by trial number, concatenate
    # along the time axis, and write one BIDS recording per group with an
    # events.tsv marking each word onset.
    #
    # BIDS entity mapping:
    #   subject = sub1 / sub2
    #   task    = chinese / english / digit  (the speech task)
    #   acq     = lfs / hga / bbs            (the feature extraction band)

    extract_dir = input_dir / "extracted"
    combo_dirs = sorted(d for d in extract_dir.iterdir() if d.is_dir())
    logger.info("Found %d subject/feature/task combinations", len(combo_dirs))

    n_ok = 0
    n_fail = 0
    for combo_dir in combo_dirs:
        parts = combo_dir.name.split("_")
        if len(parts) < 3:
            logger.warning("Cannot parse dir: %s", combo_dir.name)
            n_fail += 1
            continue

        sub = parts[0].lower()  # sub1 or sub2
        feature = parts[1].lower()  # lfs, hga, bbs
        task = parts[2].lower()  # chinese, english, digit

        seeg_files = sorted(combo_dir.glob("*_SEEG.npy"))
        if not seeg_files:
            logger.warning("No SEEG files in %s", combo_dir.name)
            n_fail += 1
            continue

        # Sort by trial number (first number in filename)
        def trial_sort_key(p):
            m = re.match(r"(\d+)_(\d+)_", p.name)
            return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

        seeg_files = sorted(seeg_files, key=trial_sort_key)

        try:
            # Concatenate all trials: each is (n_times, n_channels)
            arrays = []
            events_rows = []
            onset_sample = 0
            for npy_path in seeg_files:
                trial_data = np.load(str(npy_path))  # (n_times, n_channels)
                n_times, n_ch = trial_data.shape
                # Parse word label from filename: e.g. "1_001_APPLE_CN_SEEG.npy"
                name_parts = npy_path.stem.replace("_SEEG", "").split("_")
                word = (
                    "_".join(name_parts[2:-1])
                    if len(name_parts) > 3
                    else name_parts[2]
                    if len(name_parts) > 2
                    else "unknown"
                )
                lang = name_parts[-1] if len(name_parts) > 3 else task

                events_rows.append(
                    {
                        "onset": onset_sample / SFREQ,
                        "duration": n_times / SFREQ,
                        "trial_type": word,
                        "language": lang,
                    }
                )
                arrays.append(trial_data)
                onset_sample += n_times

            # Stack: (total_times, n_channels) -> transpose to (n_channels, total_times)
            concat = np.concatenate(arrays, axis=0)  # (total_times, n_ch)
            concat = concat.T  # (n_ch, total_times) — MNE expects this

            n_ch = concat.shape[0]
            ch_names = [f"sEEG{i:03d}" for i in range(n_ch)]
            ch_types = ["seeg"] * n_ch
            info = mne.create_info(
                ch_names, sfreq=SFREQ, ch_types=ch_types, verbose=False
            )
            raw = mne.io.RawArray(concat, info, verbose=False)

            # Use task for the speech task, acquisition for the feature band
            bids_path = mne_bids.BIDSPath(
                subject=sub.replace("sub", ""),
                task=task,
                acquisition=feature,
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

            # Write events.tsv with word-level onsets
            events_df = pd.DataFrame(events_rows)
            events_path = bids_path.copy().update(suffix="events", extension=".tsv")
            events_df.to_csv(str(events_path.fpath), sep="\t", index=False)

            total_secs = concat.shape[1] / 200.0
            logger.info(
                "OK %s_%s_%s: %d ch, %d trials, %.1f sec",
                sub,
                feature,
                task,
                n_ch,
                len(seeg_files),
                total_secs,
            )
            n_ok += 1

        except Exception as exc:
            logger.warning("FAILED %s_%s_%s: %s", sub, feature, task, exc)
            n_fail += 1

    # Self-deposit the conversion script into /code/ for provenance.
    code_dir = output_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).resolve()
    if script_path.exists():
        shutil.copy2(script_path, code_dir / script_path.name)
        logger.info("Copied %s into code/", script_path.name)

    logger.info(
        "Done: %d ok, %d failed (out of %d combos)", n_ok, n_fail, len(combo_dirs)
    )


def main():
    parser = argparse.ArgumentParser(description="Convert CerebroVoice to BIDS-iEEG")
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
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
    convert_cerebrovoice(
        args.input,
        args.output,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
