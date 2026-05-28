#!/usr/bin/env python3
from __future__ import annotations

"""Convert the Khan2022 NMT dataset to BIDS-EEG format.

The NMT (Neurodiagnostic Montage Template) dataset contains 2,417 clinical EEG
recordings in EDF format from Zenodo, with normal/abnormal labels.
19 EEG channels + 2 reference channels, standard 10-20 montage.

Usage:
    python convert_khan2022.py --input /tmp/khan2022 --output /tmp/khan2022_bids

Reference:
    Khan, H.A. et al. (2022). NMT scalp EEG dataset. Zenodo.
    https://zenodo.org/records/10909103
"""

import argparse
import json
import logging
import zipfile
from pathlib import Path

import mne
import mne_bids

logger = logging.getLogger(__name__)


def write_dataset_description(bids_root: Path):
    desc = {
        "Name": "NMT: Neurodiagnostic Montage Template Scalp EEG",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "CC BY-SA 4.0",
        "Authors": ["Hussain A. Khan"],
        "DatasetDOI": "doi:10.5281/zenodo.10909103",
        "ReferencesAndLinks": [
            "https://zenodo.org/records/10909103",
        ],
        "HowToAcknowledge": "Please cite the Zenodo record: Khan, H.A. (2022). NMT Scalp EEG Dataset.",
        "SourceDatasets": [{"URL": "https://zenodo.org/records/10909103"}],
        "GeneratedBy": [
            {
                "Name": "convert_khan2022.py (EEGDash)",
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    readme = """\
NMT: Neurodiagnostic Montage Template Scalp EEG Dataset
=========================================================

Overview
--------
2,417 clinical EEG recordings (normal and abnormal) in standard 10-20
montage with 19 EEG channels + 2 reference electrodes. EDF format,
variable sampling rates and durations.

This dataset was collected for EEG-based pathology detection and
normal/abnormal classification tasks.

Source: Zenodo (doi:10.5281/zenodo.10909103)
License: CC BY-SA 4.0
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def convert_khan2022(
    input_dir: Path,
    output_dir: Path,
    max_subjects: int | None = None,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check if we need to unzip
    zip_path = input_dir / "NMT.zip"
    nmt_dir = input_dir / "NMT"
    if zip_path.exists() and not nmt_dir.exists():
        logger.info("Extracting NMT.zip...")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(input_dir)

    # Find all EDF files
    edf_files = (
        sorted(nmt_dir.rglob("*.edf"))
        if nmt_dir.exists()
        else sorted(input_dir.rglob("*.edf"))
    )
    logger.info("Found %d EDF files", len(edf_files))

    if max_subjects:
        edf_files = edf_files[:max_subjects]

    if dry_run:
        for f in edf_files[:10]:
            print(f"  {f.name}")
        print(f"... total: {len(edf_files)}")
        return

    write_dataset_description(output_dir)
    write_readme(output_dir)

    n_ok = 0
    n_fail = 0
    for i, edf_path in enumerate(edf_files):
        sub_num = f"{i + 1:04d}"

        try:
            raw = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)

            bids_path = mne_bids.BIDSPath(
                subject=sub_num,
                task="clinical",
                datatype="eeg",
                root=output_dir,
            )

            mne_bids.write_raw_bids(
                raw,
                bids_path,
                overwrite=overwrite,
                verbose=verbose,
                allow_preload=True,
                format="EDF",
            )

            # Update sidecar
            sf = bids_path.copy().update(suffix="eeg", extension=".json").fpath
            if sf.exists():
                with open(sf) as f:
                    s = json.load(f)
                s.update(
                    {
                        "TaskName": "clinical",
                        "TaskDescription": "Clinical EEG recording (resting/routine)",
                        "EEGPlacementScheme": "10-20",
                        "PowerLineFrequency": 50,
                        "HardwareFilters": "n/a",
                        "SoftwareVersions": "n/a",
                        "DeviceSerialNumber": "n/a",
                        "CogAtlasID": "n/a",
                        "CogPOID": "n/a",
                        "MISCChannelCount": 0,
                        "OriginalFilename": edf_path.name,
                    }
                )
                with open(sf, "w") as f:
                    json.dump(s, f, indent=2)
                    f.write("\n")

            n_ok += 1
            if (i + 1) % 100 == 0:
                logger.info(
                    "Progress: %d/%d (%.0f%%)",
                    i + 1,
                    len(edf_files),
                    (i + 1) / len(edf_files) * 100,
                )

        except Exception as exc:
            logger.warning("FAILED %s: %s", edf_path.name, exc)
            n_fail += 1

    logger.info("Done: %d ok, %d failed", n_ok, n_fail)


def main():
    parser = argparse.ArgumentParser(description="Convert Khan2022 NMT to BIDS")
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument("--max-subjects", "-n", type=int, default=None)
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
    convert_khan2022(
        args.input,
        args.output,
        args.max_subjects,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
