#!/usr/bin/env python3
from __future__ import annotations

"""Convert the Brain Treebank iEEG dataset to BIDS-iEEG format.

The Brain Treebank is a large-scale dataset of intracranial electrophysiological
recordings from 10 epilepsy patients (at Boston Children's Hospital) watching
Hollywood movies. Recordings at 2048 Hz from on average 168 electrodes per
subject (1,688 electrodes total), totalling 43 hours across 26 trials.

Raw data is distributed as per-trial HDF5 files (.h5.zip) from braintreebank.dev.
Each HDF5 contains one group 'data/' with per-electrode 1D float64 arrays.

Reference:
    Wang, C., Yaari, A. U., Singh, A. K., Subramaniam, V., Rosenfarb, D.,
    DeWitt, J., Misra, P., Madsen, J. R., Stone, S., Kreiman, G., Katz, B.,
    Cases, I., & Barbu, A. (2024). Brain Treebank: Large-scale intracranial
    recordings from naturalistic language stimuli. Advances in Neural
    Information Processing Systems 37 (NeurIPS 2024, Datasets and Benchmarks
    Track). arXiv:2411.08343. https://braintreebank.dev/

Ethics: All experiments approved by Boston Children's Hospital / Harvard IRB;
carried out with the subjects' informed consent.

License: CC BY 4.0

Usage:
    python convert_braintreebank.py --input /tmp/braintreebank --output /tmp/btb_bids
    python convert_braintreebank.py --input /tmp/braintreebank --output /tmp/btb_bids --dry-run
"""

import argparse
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

import h5py
import mne
import mne_bids
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SFREQ = 2048.0  # Raw sampling rate (Hz), from code release
# (conf/data/decoding_base.yaml: samp_frequency: 2048)

# Trial manifest: subject → list of trial IDs
TRIALS = {
    1: [0, 1, 2],
    2: [0, 1, 2, 3, 4, 5, 6],
    3: [0, 1, 2],
    4: [0, 1, 2],
    5: [0],
    6: [0, 1, 4],
    7: [0, 1],
    8: [0],
    9: [0],
    10: [0, 1],
}

DATASET_DESCRIPTION = {
    "Name": (
        "Wang et al. 2024 — Brain Treebank: Large-scale intracranial "
        "recordings from naturalistic language stimuli"
    ),
    "BIDSVersion": "1.9.0",
    "HEDVersion": "8.2.0",
    "DatasetType": "raw",
    "License": "CC BY 4.0",
    "Authors": [
        "Christopher Wang",
        "Adam Yaari",
        "Aaditya K Singh",
        "Vighnesh Subramaniam",
        "Dana Rosenfarb",
        "Jan DeWitt",
        "Pranav Misra",
        "Joseph R Madsen",
        "Scellig Stone",
        "Gabriel Kreiman",
        "Boris Katz",
        "Ignacio Cases",
        "Andrei Barbu",
    ],
    "DatasetDOI": "doi:10.48550/arXiv.2411.08343",
    "EthicsApprovals": [
        "Boston Children's Hospital / Harvard IRB (all subjects gave informed consent)"
    ],
    "InstitutionName": "Boston Children's Hospital",
    "ReferencesAndLinks": [
        "https://arxiv.org/abs/2411.08343",
        "https://proceedings.neurips.cc/paper_files/paper/2024/hash/aefa2385b3f33abf1526ae4e2c208cd9-Abstract-Datasets_and_Benchmarks_Track.html",
        "https://braintreebank.dev/",
        "https://github.com/czlwang/brain_treebank_code_release",
    ],
    "HowToAcknowledge": (
        "Please cite: Wang, C., Yaari, A. U., Singh, A. K., Subramaniam, V., "
        "Rosenfarb, D., DeWitt, J., Misra, P., Madsen, J. R., Stone, S., "
        "Kreiman, G., Katz, B., Cases, I., & Barbu, A. (2024). Brain Treebank: "
        "Large-scale intracranial recordings from naturalistic language stimuli. "
        "Advances in Neural Information Processing Systems 37 (NeurIPS 2024, "
        "Datasets and Benchmarks Track). arXiv:2411.08343. "
        "https://braintreebank.dev/"
    ),
    "SourceDatasets": [{"URL": "https://braintreebank.dev/"}],
    "GeneratedBy": [
        {
            "Name": "convert_braintreebank.py (EEGDash)",
            "Description": (
                "Converted per-trial HDF5 files (raw 2048 Hz iEEG) to "
                "BIDS-iEEG BrainVision format. Each trial (one movie) "
                "becomes one BIDS run. Electrode labels from the "
                "Brain Treebank metadata (electrode_labels/sub_X/). "
                "Corrupted electrodes flagged from corrupted_elec.json."
            ),
            "CodeURL": "https://github.com/bruaristimunha/EEGDash",
        }
    ],
    "Version": "1.0.0",
}


def load_electrode_labels(metadata_dir: Path) -> dict[int, list[str]]:
    """Load per-subject electrode labels from electrode_labels/sub_X/electrode_labels.json."""
    labels = {}
    elec_dir = metadata_dir / "electrode_labels"
    if not elec_dir.exists():
        return labels
    for sub_dir in sorted(elec_dir.iterdir()):
        if not sub_dir.is_dir():
            continue
        m = re.search(r"sub_(\d+)", sub_dir.name)
        if not m:
            continue
        sub_id = int(m.group(1))
        jf = sub_dir / "electrode_labels.json"
        if jf.exists():
            with open(jf) as f:
                data = json.load(f)
            if isinstance(data, list):
                labels[sub_id] = data
                logger.debug("  sub_%d: %d electrode labels", sub_id, len(data))
    return labels


def load_corrupted_electrodes(metadata_dir: Path) -> dict[str, list[int]]:
    """Load corrupted electrode indices per subject."""
    path = metadata_dir / "corrupted_elec.json"
    if not path.exists():
        # Try parent directory
        path = metadata_dir.parent / "corrupted_elec.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def load_trial_metadata(metadata_dir: Path) -> dict[str, dict]:
    """Load per-trial metadata (movie title, etc.)."""
    meta = {}
    sub_meta_dir = metadata_dir / "subject_metadata"
    if not sub_meta_dir.exists():
        return meta
    for jf in sorted(sub_meta_dir.glob("*.json")):
        with open(jf) as f:
            meta[jf.stem] = json.load(f)
    return meta


def convert_trial(
    h5_zip_path: Path,
    sub_id: int,
    trial_id: int,
    output_dir: Path,
    electrode_labels: list[str] | None,
    corrupted: list[int] | None,
    trial_meta: dict | None,
    *,
    overwrite: bool = True,
    verbose: bool = False,
    temp_dir: Path | None = None,
) -> bool:
    """Convert one trial HDF5 to BIDS-iEEG."""
    temp_dir = temp_dir or h5_zip_path.parent / "tmp_extract"
    temp_dir.mkdir(exist_ok=True)

    # Extract HDF5
    logger.info("Extracting %s...", h5_zip_path.name)
    try:
        with zipfile.ZipFile(h5_zip_path) as zf:
            zf.extractall(temp_dir)
    except Exception as exc:
        logger.error("Failed to extract %s: %s", h5_zip_path.name, exc)
        return False

    h5_files = list(temp_dir.rglob("*.h5"))
    if not h5_files:
        logger.error("No .h5 file found in %s", h5_zip_path.name)
        return False

    h5_file = h5_files[0]

    try:
        with h5py.File(h5_file, "r") as f:
            data_grp = f["data"]
            # Sort electrode keys numerically
            elec_keys = sorted(data_grp.keys(), key=lambda k: int(k.split("_")[1]))
            n_ch = len(elec_keys)

            # Read all electrodes into a single array
            # Each electrode is (n_samples,) float64
            n_samples = data_grp[elec_keys[0]].shape[0]
            logger.info(
                "  sub-%02d trial-%03d: %d channels, %d samples (%.1f min)",
                sub_id,
                trial_id,
                n_ch,
                n_samples,
                n_samples / SFREQ / 60,
            )

            # Use electrode labels if available, otherwise use IDs.
            # Clean special chars (* / spaces) from labels — MNE and BIDS
            # don't handle them well in channel names.
            if electrode_labels and len(electrode_labels) == n_ch:
                ch_names = [
                    l.replace("*", "x").replace("/", "-").replace(" ", "")
                    for l in electrode_labels
                ]
            else:
                ch_names = [f"iEEG{int(k.split('_')[1]):03d}" for k in elec_keys]
                if electrode_labels:
                    logger.warning(
                        "  Electrode label count mismatch: %d labels vs %d channels. Using IDs.",
                        len(electrode_labels),
                        n_ch,
                    )

            # Load data: (n_ch, n_samples) — read one electrode at a time
            data = np.empty((n_ch, n_samples), dtype=np.float32)
            for i, key in enumerate(elec_keys):
                data[i] = data_grp[key][:].astype(np.float32)

        # Scale: data is in µV, MNE expects V for iEEG.
        # Use float32 scalar to avoid upcasting to float64 (saves ~8 GB per trial).
        data *= np.float32(1e-6)  # µV → V, stays float32

        ch_types = ["seeg"] * n_ch
        info = mne.create_info(ch_names, sfreq=SFREQ, ch_types=ch_types, verbose=False)

        # For large trials (>8 GB), write BrainVision manually via pybv
        # to avoid MNE's internal float64 upcast which doubles memory.
        # Threshold: 156 ch × 14M samples × 8 bytes (float64) = 17.5 GB > 36 GB RAM with overhead
        estimated_f64_gb = n_ch * n_samples * 8 / 1e9
        if estimated_f64_gb > 12:
            logger.info(
                "  Large trial (%.1f GB as f64) — using chunked write", estimated_f64_gb
            )
            import gc

            # Write BrainVision directly via pybv (avoids MNE float64 copy)
            import pybv

            bids_path = mne_bids.BIDSPath(
                subject=f"{sub_id:02d}",
                task="movie",
                run=f"{trial_id + 1:02d}",
                datatype="ieeg",
                root=output_dir,
            )
            ieeg_dir = output_dir / f"sub-{sub_id:02d}" / "ieeg"
            ieeg_dir.mkdir(parents=True, exist_ok=True)

            fname = f"sub-{sub_id:02d}_task-movie_run-{trial_id + 1:02d}_ieeg"
            # pybv writes BrainVision from float32 without float64 copy
            pybv.write_brainvision(
                data=data,  # (n_ch, n_samples) float32
                sfreq=SFREQ,
                ch_names=ch_names,
                fname_base=fname,
                folder_out=str(ieeg_dir),
                overwrite=overwrite,
            )

            # Write minimal sidecar JSON
            sidecar = {
                "TaskName": "movie",
                "SamplingFrequency": SFREQ,
                "SEEGChannelCount": n_ch,
                "RecordingType": "continuous",
                "iEEGReference": "unknown",
                "PowerLineFrequency": 60,
            }
            movie_title = trial_meta.get("title", "") if trial_meta else ""
            if movie_title:
                sidecar["TaskDescription"] = (
                    f"Participant watched the movie '{movie_title}' while "
                    f"intracranial EEG was recorded at {SFREQ:.0f} Hz."
                )
                sidecar["StimulusPresentation"] = {
                    "SoftwareName": "Movie playback",
                    "StimulusType": "movie",
                    "MovieTitle": movie_title,
                }
            with open(ieeg_dir / f"{fname}.json", "w") as sf:
                json.dump(sidecar, sf, indent=2)
                sf.write("\n")

            # Write channels.tsv
            ch_df = pd.DataFrame(
                {
                    "name": ch_names,
                    "type": ch_types,
                    "units": ["µV"] * n_ch,
                    "status": [
                        "bad" if c in (corrupted or []) else "good" for c in ch_names
                    ],
                }
            )
            ch_df.to_csv(
                ieeg_dir
                / f"{fname}_channels.tsv".replace("_ieeg_channels", "_channels"),
                sep="\t",
                index=False,
            )

            # Write participants.tsv if missing
            part_path = output_dir / "participants.tsv"
            if not part_path.exists():
                pd.DataFrame({"participant_id": [f"sub-{sub_id:02d}"]}).to_csv(
                    part_path, sep="\t", index=False
                )

            del data
            gc.collect()

            logger.info("  OK (chunked) → %s/%s", ieeg_dir.name, fname)
            return True

        raw = mne.io.RawArray(data, info, verbose=False)

        # Mark corrupted electrodes as bad.
        # The corrupted list contains electrode NAMES (strings), not indices.
        # Clean the names the same way we cleaned ch_names above.
        if corrupted:
            corrupted_clean = [
                c.replace("*", "x").replace("/", "-").replace(" ", "")
                for c in corrupted
            ]
            bad_names = [c for c in corrupted_clean if c in ch_names]
            raw.info["bads"] = bad_names
            if bad_names:
                logger.info(
                    "  Marked %d bad channels: %s", len(bad_names), bad_names[:5]
                )

        # Determine task name from movie metadata
        task = "movie"
        movie_title = ""
        if trial_meta:
            movie_title = trial_meta.get("title", "")
            # Clean movie title for use in annotations
            task = "movie"  # Keep task generic, movie title goes in sidecar

        bids_path = mne_bids.BIDSPath(
            subject=f"{sub_id:02d}",
            task=task,
            run=f"{trial_id + 1:02d}",  # BIDS runs are 1-indexed
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

        # Write movie metadata as task description in the sidecar JSON
        if movie_title:
            sidecar_path = bids_path.copy().update(suffix="ieeg", extension=".json")
            sidecar_file = sidecar_path.fpath
            if sidecar_file.exists():
                with open(sidecar_file) as sf:
                    sidecar = json.load(sf)
                sidecar["TaskDescription"] = (
                    f"Participant watched the movie '{movie_title}' while "
                    f"intracranial EEG was recorded at {SFREQ:.0f} Hz."
                )
                sidecar["StimulusPresentation"] = {
                    "SoftwareName": "Movie playback",
                    "StimulusType": "movie",
                    "MovieTitle": movie_title,
                }
                with open(sidecar_file, "w") as sf:
                    json.dump(sidecar, sf, indent=2)
                    sf.write("\n")

        # Free memory
        del data, raw

        logger.info("  OK → %s", bids_path)
        return True

    except Exception as exc:
        logger.error("  FAILED sub-%02d trial-%03d: %s", sub_id, trial_id, exc)
        return False
    finally:
        # Clean up extracted H5 to save disk
        for h5f in temp_dir.rglob("*.h5"):
            h5f.unlink()


def convert_braintreebank(
    input_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
    subjects: list[int] | None = None,
):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write dataset description
    with open(output_dir / "dataset_description.json", "w") as f:
        json.dump(DATASET_DESCRIPTION, f, indent=2)
        f.write("\n")

    # Extract metadata
    metadata_dir = input_dir / "metadata"
    if not metadata_dir.exists():
        # Metadata might be in input_dir directly
        metadata_dir = input_dir

    electrode_labels = load_electrode_labels(metadata_dir)
    corrupted = load_corrupted_electrodes(metadata_dir)
    trial_meta = load_trial_metadata(metadata_dir)

    logger.info("Electrode labels for %d subjects", len(electrode_labels))
    logger.info("Corrupted electrode info for %d subjects", len(corrupted))
    logger.info("Trial metadata for %d trials", len(trial_meta))

    # Process trials
    trials_to_process = subjects if subjects else sorted(TRIALS.keys())
    n_ok = 0
    n_fail = 0
    temp_dir = input_dir / "tmp_extract"

    for sub_id in trials_to_process:
        trial_list = TRIALS.get(sub_id, [])
        sub_labels = electrode_labels.get(sub_id)
        sub_corrupted = corrupted.get(f"sub_{sub_id}", [])

        for trial_id in trial_list:
            fname = f"sub_{sub_id}_trial{trial_id:03d}.h5.zip"
            h5_zip = input_dir / fname
            if not h5_zip.exists():
                logger.warning("Missing: %s", fname)
                n_fail += 1
                continue

            meta_key = f"sub_{sub_id}_trial{trial_id:03d}_metadata"
            tmeta = trial_meta.get(meta_key)

            if dry_run:
                movie = tmeta.get("title", "?") if tmeta else "?"
                logger.info(
                    "[DRY] sub-%02d run-%02d: %s (%s)",
                    sub_id,
                    trial_id + 1,
                    fname,
                    movie,
                )
                continue

            ok = convert_trial(
                h5_zip,
                sub_id,
                trial_id,
                output_dir,
                sub_labels,
                sub_corrupted,
                tmeta,
                overwrite=overwrite,
                verbose=verbose,
                temp_dir=temp_dir,
            )
            if ok:
                n_ok += 1
            else:
                n_fail += 1

    # Copy metadata to /code/
    code_dir = output_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)

    # Copy transcripts and trees
    for zipname in ["transcripts.zip", "trees.zip"]:
        src = input_dir / zipname
        if src.exists():
            shutil.copy2(src, code_dir / zipname)
            logger.info("Copied %s to code/", zipname)

    # Self-deposit script
    script_path = Path(__file__).resolve()
    if script_path.exists():
        shutil.copy2(script_path, code_dir / script_path.name)
        logger.info("Copied %s into code/", script_path.name)

    # Clean up temp
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    if not dry_run:
        logger.info("Done: %d ok, %d failed", n_ok, n_fail)


def main():
    parser = argparse.ArgumentParser(
        description="Convert Brain Treebank to BIDS-iEEG",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--subjects",
        nargs="+",
        type=int,
        default=None,
        help="Only process these subject IDs (default: all)",
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
    convert_braintreebank(
        args.input,
        args.output,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
        subjects=args.subjects,
    )


if __name__ == "__main__":
    main()
