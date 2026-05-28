#!/usr/bin/env python3
from __future__ import annotations

"""Convert the Kemp2000 Sleep-EDF Expanded dataset to BIDS-EEG format.

The Sleep-EDF Expanded database contains 197 whole-night PSG recordings from
two studies:
  - Sleep Cassette (SC): 78 healthy subjects, ~48h ambulatory recordings
  - Sleep Telemetry (ST): 22 subjects (Temazepam drug study)

Channels: EEG Fpz-Cz, EEG Pz-Oz, EOG horizontal, EMG submental (+ sometimes
respiration, body temperature). 100 Hz sampling rate.
Expert-annotated hypnograms (sleep staging: W, N1, N2, N3, REM).

Usage:
    python convert_kemp2000.py --input /tmp/kemp2000 --output /tmp/kemp2000_bids

Reference:
    Kemp, B. et al. (2000). Analysis of a sleep-dependent neuronal feedback
    loop. IEEE Trans. Biomed. Eng., 47(9), 1185-1194.
    Goldberger, A. et al. (2000). PhysioBank, PhysioToolkit, and PhysioNet.
    https://physionet.org/content/sleep-edfx/1.0.0/
"""

import argparse
import json
import logging
import re
from pathlib import Path

import mne
import mne_bids

logger = logging.getLogger(__name__)


def write_dataset_description(bids_root: Path):
    desc = {
        "Name": "Sleep-EDF Expanded: Whole-Night PSG Recordings",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "ODbL v1.0",
        "Authors": [
            "Bob Kemp",
            "Aeilko H. Zwinderman",
            "Bert Tuk",
            "Hilbert A.C. Kamphuisen",
            "Josefien J.L. Oberye",
        ],
        "Funding": ["Netherlands Organization for Scientific Research (NWO)"],
        "DatasetDOI": "doi:10.13026/C2X676",
        "ReferencesAndLinks": [
            "https://physionet.org/content/sleep-edfx/1.0.0/",
            "https://doi.org/10.1109/10.867928",
        ],
        "HowToAcknowledge": (
            "Please cite: Kemp, B. et al. (2000). IEEE Trans. Biomed. Eng., "
            "47(9), 1185-1194. And: Goldberger, A. et al. (2000). PhysioBank, "
            "PhysioToolkit, and PhysioNet. Circulation, 101(23), e215-e220."
        ),
        "SourceDatasets": [{"URL": "https://physionet.org/content/sleep-edfx/1.0.0/"}],
        "GeneratedBy": [
            {
                "Name": "convert_kemp2000.py (EEGDash)",
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    readme = """\
Sleep-EDF Expanded: Whole-Night Polysomnographic Recordings
=============================================================

Overview
--------
197 whole-night polysomnographic (PSG) recordings from PhysioNet, comprising
two studies:

1. Sleep Cassette (SC) study: 78 healthy subjects (aged 25-101), two ~20-hour
   ambulatory recordings per subject with ~48-hour interval. Recordings include
   EEG (Fpz-Cz, Pz-Oz at 100 Hz), EOG (horizontal), and submental chin EMG.

2. Sleep Telemetry (ST) study: 22 subjects, placebo-controlled Temazepam drug
   study. Two overnight hospital PSG recordings per subject. Includes EEG,
   EOG, EMG, plus event markers and body temperature.

Sleep Staging
-------------
Expert-annotated hypnograms using Rechtschaffen & Kales standard:
- W: Wake
- N1: NREM stage 1 (originally S1)
- N2: NREM stage 2 (originally S2)
- N3: NREM stage 3/4 (originally S3+S4, combined as N3 per AASM)
- REM: Rapid Eye Movement sleep
- ?: Movement time / unknown

Recording Setup
---------------
- EEG: Fpz-Cz and Pz-Oz (100 Hz)
- EOG: Horizontal (100 Hz)
- EMG: Submental chin (1 Hz in SC study, 100 Hz in ST study)
- Format: EDF (European Data Format)

Reference
---------
Kemp, B. et al. (2000). IEEE Trans. Biomed. Eng., 47(9), 1185-1194.
https://physionet.org/content/sleep-edfx/1.0.0/
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def convert_kemp2000(
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

    # Find PSG EDF files (not hypnogram files)
    data_dir = input_dir / "physionet-sleep-data"
    if not data_dir.exists():
        data_dir = input_dir

    psg_files = sorted([f for f in data_dir.glob("*-PSG.edf")])
    hyp_files = sorted([f for f in data_dir.glob("*-Hypnogram.edf")])

    logger.info(
        "Found %d PSG files, %d hypnogram files", len(psg_files), len(hyp_files)
    )

    # Build hypnogram lookup
    hyp_map = {}
    for h in hyp_files:
        # SC4001EC-Hypnogram.edf → key = SC4001
        key = h.name.split("-")[0][:6]
        hyp_map[key] = h

    if dry_run:
        for f in psg_files[:10]:
            print(f"  {f.name}")
        print(f"... total: {len(psg_files)}")
        return

    write_dataset_description(output_dir)
    write_readme(output_dir)

    n_ok = 0
    n_fail = 0
    for i, psg_path in enumerate(psg_files):
        fname = psg_path.name  # e.g., SC4001E0-PSG.edf

        # Parse subject and session from filename
        # SC4ssNE0 → study=SC, subject=ss, night=N
        # ST7ssNJ0 → study=ST, subject=ss, night=N
        match = re.match(r"(SC4|ST7)(\d{2})(\d)", fname)
        if not match:
            logger.warning("Cannot parse filename: %s", fname)
            n_fail += 1
            continue

        study = "cassette" if match.group(1) == "SC4" else "telemetry"
        sub_num = match.group(2)
        night = match.group(3)
        sub_id = f"{study}{sub_num}"
        ses_id = f"night{night}"
        task = "sleep"

        try:
            raw = mne.io.read_raw_edf(str(psg_path), preload=False, verbose=False)

            # Load hypnogram annotations if available
            key = fname.split("-")[0][:6]
            if key in hyp_map:
                hyp = mne.read_annotations(str(hyp_map[key]))
                raw.set_annotations(hyp)

            bids_path = mne_bids.BIDSPath(
                subject=sub_id,
                session=ses_id,
                task=task,
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

            # Update sidecar
            sf = bids_path.copy().update(suffix="eeg", extension=".json").fpath
            if sf.exists():
                with open(sf) as f:
                    s = json.load(f)
                s.update(
                    {
                        "TaskName": task,
                        "TaskDescription": f"Whole-night sleep recording ({study} study)",
                        "Instructions": "Sleep naturally",
                        "InstitutionName": "Westeinde Hospital, The Hague"
                        if study == "cassette"
                        else "Hospital de la Ribera, Alzira",
                        "PowerLineFrequency": 50,
                        "HardwareFilters": "n/a",
                        "SoftwareVersions": "n/a",
                        "DeviceSerialNumber": "n/a",
                        "CogAtlasID": "n/a",
                        "CogPOID": "n/a",
                        "MISCChannelCount": 0,
                        "StudyType": study,
                        "OriginalFilename": fname,
                    }
                )
                with open(sf, "w") as f:
                    json.dump(s, f, indent=2)
                    f.write("\n")

            n_ok += 1
            if (i + 1) % 20 == 0:
                logger.info(
                    "Progress: %d/%d (%.0f%%)",
                    i + 1,
                    len(psg_files),
                    (i + 1) / len(psg_files) * 100,
                )

        except Exception as exc:
            logger.warning("FAILED %s: %s", fname, exc)
            n_fail += 1

    logger.info("Done: %d ok, %d failed", n_ok, n_fail)


def main():
    parser = argparse.ArgumentParser(description="Convert Sleep-EDF to BIDS")
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
    convert_kemp2000(
        args.input,
        args.output,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
