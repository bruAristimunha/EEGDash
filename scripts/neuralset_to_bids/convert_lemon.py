#!/usr/bin/env python3
from __future__ import annotations

"""Convert the LEMON EEG dataset (Babayan et al., 2019) to BIDS-EEG format.

The LEMON dataset contains resting-state EEG (eyes open/closed alternating)
from 215 healthy subjects recorded with BrainVision actiCHamp at 2500 Hz,
62 EEG channels, standard 10-20 montage.

The raw data from GWDG FTP is already in BrainVision format (.vhdr/.eeg/.vmrk)
with BIDS-style subject IDs but non-compliant directory structure. This script
restructures to proper BIDS layout and adds required sidecars.

Usage:
    python convert_lemon.py --input /tmp/lemon_eeg --output /tmp/lemon_bids
    python convert_lemon.py --input /tmp/lemon_eeg --output /tmp/lemon_bids --subjects sub-010002
    python convert_lemon.py --input /tmp/lemon_eeg --output /tmp/lemon_bids --dry-run

Reference:
    Babayan, A. et al. (2019). A mind-brain-body dataset of MRI, EEG,
    cognition, emotion, and peripheral physiology in young and old adults.
    Scientific Data, 6, 180308. https://doi.org/10.1038/sdata.2018.308
"""

import argparse
import json
import logging
from pathlib import Path

import mne
import mne_bids

logger = logging.getLogger(__name__)

TASK = "resting"
SFREQ = 2500.0

# VEOG channel needs to be retyped from EEG to EOG
CHANNEL_TYPE_OVERRIDES = {"VEOG": "eog"}


def write_dataset_description(bids_root: Path):
    desc = {
        "Name": "LEMON: MPI Leipzig Mind-Brain-Body EEG (Resting State)",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "CC BY 4.0",
        "Authors": [
            "Anahit Babayan",
            "Miray Erbey",
            "Deniz Kumral",
            "Janis D. Reinelt",
            "Andrea M.F. Reiter",
            "Josefin Röbbig",
            "H. Lina Schaare",
            "Marie Uhlig",
            "Alfred Anwander",
            "Pierre-Louis Bazin",
            "Annette Horstmann",
            "Leonie Lampe",
            "Vadim V. Nikulin",
            "Hadas Okon-Singer",
            "Sven Preusser",
            "Andre Pampel",
            "Christiane S. Rohr",
            "Julia Sacher",
            "Angelika Thone-Otto",
            "Sabrina Trapp",
            "Till Nierhaus",
            "Denise Altmann",
            "Katrin Arelin",
            "Maria Blochl",
            "Edith Bongartz",
            "Patric Breig",
            "Elena Cesnaite",
            "Sufang Chen",
            "Roberto Cozatl",
            "Saskia Czerwonatis",
            "Gabriele Dambrauskaite",
            "Maria Dreyer",
            "Jessica Enders",
            "Melina Engelhardt",
            "Marie Michele Fischer",
            "Norman Forschack",
            "Johannes Golchert",
            "Laura Golz",
            "C. Alexandrina Guran",
            "Susanna Hedrich",
            "Nicole Hentschel",
            "Daria I. Hoffmann",
            "Julia M. Huntenburg",
            "Rebecca Jost",
            "Anna Kosatschek",
            "Stella Kunzendorf",
            "Hannah Lammers",
            "Mark E. Lauckner",
            "Keyvan Mahjoory",
            "Natacha Mendes",
            "Ramona Menger",
            "Enzo Morino",
            "Karina Nathe",
            "Jennifer Neubauer",
            "Handan Noyan",
            "Sabine Oligschlager",
            "Patricia Panczyszyn-Trzewik",
            "Dorothee Poehlchen",
            "Nadine Putzke",
            "Sabrina Roski",
            "Marie-Catherine Schaller",
            "Anja Schieferbein",
            "Benito Schlaak",
            "Hanna Maria Schmidt",
            "Robert Schmidt",
            "Anne Schrimpf",
            "Sylvia Stasch",
            "Maria Voss",
            "Anett Wiedemann",
            "Daniel S. Margulies",
            "Michael Gaebler",
            "Arno Villringer",
        ],
        "Funding": [
            "Max Planck Society",
            "German Research Foundation (CRC 1052 Obesity Mechanisms)",
            "European Union (ERC-2016-StG-Self-Control-677804)",
        ],
        "DatasetDOI": "doi:10.1038/sdata.2018.308",
        "ReferencesAndLinks": [
            "https://doi.org/10.1038/sdata.2018.308",
            "https://ftp.gwdg.de/pub/misc/MPI-Leipzig_Mind-Brain-Body-LEMON/",
        ],
        "HowToAcknowledge": (
            "Please cite: Babayan, A. et al. (2019). A mind-brain-body dataset "
            "of MRI, EEG, cognition, emotion, and peripheral physiology in "
            "young and old adults. Scientific Data, 6, 180308."
        ),
        "SourceDatasets": [
            {
                "URL": "https://ftp.gwdg.de/pub/misc/MPI-Leipzig_Mind-Brain-Body-LEMON/EEG_MPILMBB_LEMON/EEG_Raw_BIDS_ID/",
            }
        ],
        "GeneratedBy": [
            {
                "Name": "convert_lemon.py (EEGDash)",
                "Description": "Restructured from GWDG FTP BrainVision files to BIDS-EEG layout.",
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path):
    readme = """\
LEMON: MPI Leipzig Mind-Brain-Body EEG Dataset (Resting State)
===============================================================

Overview
--------
Resting-state EEG from 215 healthy participants (young and old adults) from
the Leipzig Study for Mind-Body-Emotion Interactions (LEMON). Subjects
alternated between eyes-closed (EC) and eyes-open (EO) blocks of ~60 seconds
each for approximately 16 minutes total.

Demographics: Young adults (20-35 years, N=153) and older adults (59-77 years,
N=74). All right-handed, normal or corrected-to-normal vision, no history of
neurological or psychiatric disorders.

Recording Setup
---------------
- Amplifier: BrainVision actiCHamp (Brain Products GmbH)
- Channels: 62 EEG (standard 10-20 extended, ActiCAP)
- Online reference: FCz
- Ground: AFz (inferred from BrainVision convention)
- Sampling rate: 2500 Hz
- Impedance: < 5 kOhm (active electrodes)
- Recording duration: ~16 min per subject

Task
----
Resting state with alternating eyes-open (EO) and eyes-closed (EC) blocks.
- Eyes-open: fixate on LED (off state), eyes open
- Eyes-closed: close eyes, fixate on LED (off state)
- Block duration: ~60 seconds each
- Event markers: S200 = eyes open onset, S210 = eyes closed onset

Known Issues
------------
- Subjects sub-010020, sub-010044, sub-010193, sub-010219 have incorrect .vhdr
  file paths that were fixed during conversion
- Subject sub-010203 has no marker file (.vmrk)
- 5 subjects (sub-010235, sub-010237, sub-010259, sub-010281, sub-010293)
  are absent from the dataset (not recorded)

Reference
---------
Babayan, A. et al. (2019). A mind-brain-body dataset of MRI, EEG, cognition,
emotion, and peripheral physiology in young and old adults. Scientific Data, 6,
180308. https://doi.org/10.1038/sdata.2018.308
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def convert_lemon(
    input_dir: Path,
    output_dir: Path,
    subjects: list[str] | None = None,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all subjects
    all_subjects = sorted(
        [
            d.name
            for d in input_dir.iterdir()
            if d.is_dir()
            and d.name.startswith("sub-")
            and (d / "RSEEG" / f"{d.name}.vhdr").exists()
        ]
    )
    logger.info("Found %d subjects with EEG data", len(all_subjects))

    if subjects:
        all_subjects = [s for s in all_subjects if s in subjects]
        if not all_subjects:
            raise ValueError(
                f"No subjects matched filter. Available: {sorted(all_subjects)[:5]}..."
            )

    if dry_run:
        for sub in all_subjects:
            print(f"  {sub} → sub-{sub.replace('sub-', '')}/eeg/task-{TASK}")
        print(f"Total: {len(all_subjects)} subjects")
        return

    # Write top-level BIDS files
    write_dataset_description(output_dir)
    write_readme(output_dir)

    n_ok = 0
    n_fail = 0
    for i, sub_id in enumerate(all_subjects):
        sub_num = sub_id.replace("sub-", "")
        vhdr_path = input_dir / sub_id / "RSEEG" / f"{sub_id}.vhdr"

        try:
            raw = mne.io.read_raw_brainvision(
                str(vhdr_path), preload=False, verbose=False
            )

            # Fix channel types: VEOG should be EOG, not EEG
            for ch_name, ch_type in CHANNEL_TYPE_OVERRIDES.items():
                if ch_name in raw.ch_names:
                    raw.set_channel_types({ch_name: ch_type})

            bids_path = mne_bids.BIDSPath(
                subject=sub_num,
                task=TASK,
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

            # Enrich sidecar
            _update_sidecar(bids_path)

            n_ok += 1
            if (i + 1) % 20 == 0:
                logger.info(
                    "Progress: %d/%d subjects (%.0f%%)",
                    i + 1,
                    len(all_subjects),
                    (i + 1) / len(all_subjects) * 100,
                )

        except Exception as exc:
            logger.warning("FAILED sub-%s: %s", sub_num, exc)
            n_fail += 1

    logger.info("Done: %d converted, %d failed", n_ok, n_fail)


def _update_sidecar(bids_path: mne_bids.BIDSPath):
    sidecar_path = bids_path.copy().update(suffix="eeg", extension=".json")
    fpath = sidecar_path.fpath
    if not fpath.exists():
        return

    with open(fpath) as f:
        sidecar = json.load(f)

    sidecar.update(
        {
            "TaskName": TASK,
            "TaskDescription": (
                "Resting state with alternating eyes-open and eyes-closed blocks "
                "(~60s each). Subjects fixated on an LED. S200=eyes open, S210=eyes closed."
            ),
            "Instructions": (
                "Alternate between eyes-open and eyes-closed blocks. During eyes-open, "
                "fixate on the LED. During eyes-closed, keep eyes closed."
            ),
            "InstitutionName": "Max Planck Institute for Human Cognitive and Brain Sciences",
            "InstitutionAddress": "Leipzig, Saxony, Germany",
            "InstitutionalDepartmentName": "Department of Neurology",
            "Manufacturer": "Brain Products GmbH",
            "ManufacturersModelName": "actiCHamp",
            "CapManufacturer": "Brain Products",
            "CapManufacturersModelName": "ActiCAP",
            "EEGReference": "FCz",
            "EEGGround": "AFz",
            "EEGPlacementScheme": "10-20 extended",
            "PowerLineFrequency": 50,
            "HardwareFilters": "n/a",
            "SoftwareVersions": "n/a",
            "DeviceSerialNumber": "n/a",
            "CogAtlasID": "https://www.cognitiveatlas.org/task/id/trm_4c8a834779883",
            "CogPOID": "n/a",
            "MISCChannelCount": 0,
            "StimulusPresentation": {
                "SoftwareName": "n/a",
                "ScreenDistance": "n/a",
                "ScreenRefreshRate": "n/a",
                "ScreenResolution": "n/a",
            },
        }
    )

    with open(fpath, "w") as f:
        json.dump(sidecar, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Convert LEMON EEG to BIDS format",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument("--subjects", "-s", nargs="+", default=None)
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

    convert_lemon(
        input_dir=args.input,
        output_dir=args.output,
        subjects=args.subjects,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
