#!/usr/bin/env python3
from __future__ import annotations

"""Convert the Brennan2019 Alice in Wonderland EEG dataset to BIDS-EEG format.

33 subjects listened to the first chapter of Alice in Wonderland.
61 EEG channels (FieldTrip format .mat), 500 Hz, easycap-M10 montage.

Usage:
    python convert_brennan2019.py --input /tmp/brennan2019 --output /tmp/brennan2019_bids

Reference:
    Brennan, J.R. & Hale, J.T. (2019). Hierarchical structure guides rapid
    linguistic predictions during naturalistic listening. PLoS ONE, 14(1), e0207741.
    https://doi.org/10.1371/journal.pone.0207741
"""

import argparse
import json
import logging
from pathlib import Path

import mne
import mne_bids
import numpy as np
from scipy.io import loadmat

logger = logging.getLogger(__name__)

SFREQ = 500.0


def write_dataset_description(bids_root: Path):
    desc = {
        "Name": "Brennan2019: EEG during Alice in Wonderland Listening",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "CC BY 4.0",
        "Authors": ["Jonathan R. Brennan", "John T. Hale"],
        "DatasetDOI": "doi:10.1371/journal.pone.0207741",
        "ReferencesAndLinks": [
            "https://doi.org/10.1371/journal.pone.0207741",
            "https://deepblue.lib.umich.edu/data/concern/data_sets/bg257f92t",
        ],
        "HowToAcknowledge": (
            "Please cite: Brennan, J.R. & Hale, J.T. (2019). Hierarchical "
            "structure guides rapid linguistic predictions during naturalistic "
            "listening. PLoS ONE, 14(1), e0207741."
        ),
        "SourceDatasets": [
            {"URL": "https://deepblue.lib.umich.edu/data/concern/data_sets/bg257f92t"}
        ],
        "GeneratedBy": [
            {
                "Name": "convert_brennan2019.py (EEGDash)",
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    readme = """\
Brennan2019: EEG during Alice in Wonderland Listening
=======================================================

Overview
--------
EEG recorded from 33 subjects while listening to the first chapter of
"Alice's Adventures in Wonderland" by Lewis Carroll. Naturalistic
auditory comprehension paradigm for studying hierarchical linguistic
structure processing.

Recording Setup
---------------
- Channels: 61 EEG + 1 VEOG + 1 audio channel
- Sampling rate: 500 Hz
- Montage: easycap-M10
- Reference: Average reference (offline)
- Bandpass: 0.1-200 Hz (online)

Task
----
Passive listening to continuous naturalistic speech (audiobook).
Subjects listened to the full first chapter (~25 minutes).

Reference
---------
Brennan, J.R. & Hale, J.T. (2019). PLoS ONE, 14(1), e0207741.
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def read_brennan_mat(mat_path: Path) -> mne.io.RawArray:
    """Read a Brennan2019 FieldTrip .mat file and return MNE Raw."""
    mat = loadmat(
        str(mat_path),
        squeeze_me=True,
        chars_as_strings=True,
        struct_as_record=True,
        simplify_cells=True,
    )
    raw_struct = mat["raw"]

    sfreq = float(raw_struct["hdr"]["Fs"])
    assert sfreq == SFREQ

    ch_names = list(raw_struct["hdr"]["label"])
    n_chans = int(raw_struct["hdr"]["nChans"])

    # Add audio channel if missing
    if len(ch_names) == 61:
        ch_names.append("AUD")

    # Channel types: 60 EEG + 1 VEOG + 1 misc (audio)
    ch_types = ["eeg"] * 60 + ["eog", "misc"]

    data = raw_struct["trial"]
    if data.shape[0] == n_chans and len(ch_names) > n_chans:
        data = np.vstack((data, np.zeros_like(data[0])))

    info = mne.create_info(ch_names, sfreq, ch_types, verbose=False)
    raw = mne.io.RawArray(data * 1e-6, info, verbose=False)  # uV to V

    montage = mne.channels.make_standard_montage("easycap-M10")
    raw.set_montage(montage, on_missing="ignore")

    return raw


def convert_brennan2019(
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

    # Find .mat files (subject data)
    mat_files = sorted(input_dir.glob("S*.mat"))
    if not mat_files:
        # Check in proc/ subdirectory
        mat_files = sorted((input_dir / "proc").glob("S*.mat"))
    if not mat_files:
        mat_files = sorted(input_dir.rglob("S*.mat"))

    logger.info("Found %d subject .mat files", len(mat_files))

    if dry_run:
        for f in mat_files:
            print(f"  {f.name}")
        return

    write_dataset_description(output_dir)
    write_readme(output_dir)

    n_ok = 0
    n_fail = 0
    for i, mat_path in enumerate(mat_files):
        sub_id = mat_path.stem  # e.g., "S01"
        sub_num = sub_id.replace("S", "").zfill(3)

        try:
            raw = read_brennan_mat(mat_path)

            bids_path = mne_bids.BIDSPath(
                subject=sub_num,
                task="alicelistening",
                datatype="eeg",
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

            # Update sidecar
            sf = bids_path.copy().update(suffix="eeg", extension=".json").fpath
            if sf.exists():
                with open(sf) as f:
                    s = json.load(f)
                s.update(
                    {
                        "TaskName": "alicelistening",
                        "TaskDescription": (
                            "Passive listening to chapter 1 of Alice's Adventures in "
                            "Wonderland (Lewis Carroll). Continuous naturalistic speech, ~25 min."
                        ),
                        "Instructions": "Listen to the audiobook.",
                        "InstitutionName": "University of Michigan",
                        "InstitutionAddress": "Ann Arbor, MI, USA",
                        "Manufacturer": "Brain Products GmbH",
                        "ManufacturersModelName": "actiCHamp",
                        "CapManufacturer": "easycap",
                        "CapManufacturersModelName": "M10",
                        "EEGReference": "average (offline)",
                        "EEGPlacementScheme": "easycap-M10",
                        "PowerLineFrequency": 60,
                        "HardwareFilters": "n/a",
                        "SoftwareVersions": "n/a",
                        "DeviceSerialNumber": "n/a",
                        "CogAtlasID": "n/a",
                        "CogPOID": "n/a",
                        "MISCChannelCount": 1,
                    }
                )
                with open(sf, "w") as f:
                    json.dump(s, f, indent=2)
                    f.write("\n")

            n_ok += 1
            logger.info("OK sub-%s (%d/%d)", sub_num, i + 1, len(mat_files))

        except Exception as exc:
            logger.warning("FAILED %s: %s", mat_path.name, exc)
            n_fail += 1

    logger.info("Done: %d ok, %d failed", n_ok, n_fail)


def main():
    parser = argparse.ArgumentParser(description="Convert Brennan2019 to BIDS")
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
    convert_brennan2019(
        args.input,
        args.output,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
