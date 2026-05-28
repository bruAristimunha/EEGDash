#!/usr/bin/env python3
from __future__ import annotations

"""Convert the CMI MIPDB EEG dataset to BIDS-EEG.

The Multimodal Resource for Studying Information Processing in the
Developing Brain (MIPDB) is a Child Mind Institute open-access EEG dataset
distributed via FCP-INDI:
    s3://fcp-indi/data/Projects/EEG_Eyetracking_CMI_data/

Per-subject layout (source):
    A00<id>/
        EEG/raw/raw_format/A00<id>NNN.raw          # NNN = task block index
        EEG/raw/raw_format/A00<id>.raw.IMP         # impedance log
        EEG/raw/raw_format/A00<id>.raw.GAIN        # gain log
        EEG/preprocessed/...                       # CSV/MAT preprocessed
        Behavioral/...                             # behavioral CSV/MAT
        Eyetracking/idf,txt/...                    # SMI eye tracker output

Recording setup (from Langer et al. 2017, Sci Data 4:170040):
    - EGI HydroCel Geodesic Sensor Net, 128 channels (E1..E128) +
      vertex reference (E129 = Cz)
    - Sampling rate 500 Hz
    - Per-subject paradigm sequence is fixed across subjects
      (Resting-state → Surround suppression → Naturalistic viewing →
      Contrast change detection → Sequence learning → Symbol search)
      but the paper does NOT enumerate the per-.raw-block-index
      paradigm mapping. We therefore publish each .raw block as
      `task-blockNN`; downstream code should map block N → paradigm
      after consulting CMI MIPDB documentation.

Reference:
    Langer, N., Ho, E. J., Alexander, L. M., Xu, H. Y., Jozanovic, R. K.,
    Henin, S., Petroni, A., Cohen, S., Marcelle, E. T., Parra, L. C.,
    Milham, M. P., & Kelly, S. P. (2017). A resource for assessing
    information processing in the developing brain using EEG and eye
    tracking. Scientific Data, 4, 170040.
    https://doi.org/10.1038/sdata.2017.40
    (Author byline as printed in the paper uses single-letter middle
    initials without periods: "Erica J Ho", "Helen Y Xu", etc. — the
    `Authors` field below uses that convention.)

License: CC-BY-NC-SA-3.0 (per Langer et al. 2017 / PMC5387929).

Usage:
    python convert_mipdb.py --input ~/mne_data/MIPDB --output ~/mne_data/MIPDB_bids
    python convert_mipdb.py --input ~/mne_data/MIPDB --output ~/mne_data/MIPDB_bids --dry-run
    python convert_mipdb.py --input ~/mne_data/MIPDB --output ~/mne_data/MIPDB_bids --subjects A00051826
"""

import argparse
import json
import logging
import re
import shutil
from pathlib import Path

import mne
import mne_bids
import pandas as pd

logger = logging.getLogger(__name__)


# CMI MIPDB ships per-block .raw files with a fixed numeric index (001–011).
# Langer et al. 2017 (Sci Data 4:170040) state the paradigm order is the
# same for all participants and lists 6 paradigms (Resting-state, Surround
# suppression, Naturalistic viewing, Contrast change detection, Sequence
# learning, Symbol search) but does NOT enumerate which raw block index
# corresponds to which paradigm.
#
# We therefore use generic `task-blockNN` BIDS task entities and document
# the (presumed) paradigm sequence in dataset_description.json. Once an
# authoritative per-block-index → paradigm mapping is available (e.g. via
# a CMI MIPDB documentation update), regenerate the BIDS tree with proper
# paradigm names and re-issue the dataset.


def task_for_index(idx: int) -> str:
    return f"block{idx:02d}"


def build_dataset_description() -> dict:
    """Construct dataset_description.json content for the BIDS root."""
    return {
        "Name": (
            "Langer et al. 2017 — Multimodal Resource for Studying "
            "Information Processing in the Developing Brain (MIPDB)"
        ),
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        # Langer et al. 2017 (Sci Data) is itself CC BY 4.0, but the
        # PMC5387929 page explicitly states the public MIPDB data is
        # released under "Creative Commons, Attribution Non-Commercial
        # Share Alike License (CC-BY-NC-SA 3.0)".
        # https://pmc.ncbi.nlm.nih.gov/articles/PMC5387929/
        "License": "CC-BY-NC-SA-3.0",
        "Authors": [
            "Nicolas Langer",
            "Erica J Ho",
            "Lindsay M Alexander",
            "Helen Y Xu",
            "Renee K Jozanovic",
            "Simon Henin",
            "Agustin Petroni",
            "Samantha Cohen",
            "Enitan T Marcelle",
            "Lucas C Parra",
            "Michael P Milham",
            "Simon P Kelly",
        ],
        "DatasetDOI": "doi:10.1038/sdata.2017.40",
        "EthicsApprovals": [
            "Chesapeake Institutional Review Board",
        ],
        "InstitutionName": "Child Mind Institute",
        "ReferencesAndLinks": [
            "https://doi.org/10.1038/sdata.2017.40",
            "https://fcon_1000.projects.nitrc.org/indi/cmi_eeg/",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC5387929/",
        ],
        "HowToAcknowledge": (
            "Please cite: Langer, N., Ho, E. J., Alexander, L. M., Xu, H. Y., "
            "Jozanovic, R. K., Henin, S., Petroni, A., Cohen, S., Marcelle, "
            "E. T., Parra, L. C., Milham, M. P., & Kelly, S. P. (2017). "
            "A resource for assessing information processing in the developing "
            "brain using EEG and eye tracking. Scientific Data, 4, 170040. "
            "https://doi.org/10.1038/sdata.2017.40"
        ),
        "SourceDatasets": [
            {
                "URL": "s3://fcp-indi/data/Projects/EEG_Eyetracking_CMI_data/",
                "Version": "as of 2026-04",
            }
        ],
        "GeneratedBy": [
            {
                "Name": "convert_mipdb.py (EEGDash)",
                "Description": (
                    "Read EGI NetStation .raw files at 500 Hz with "
                    "mne.io.read_raw_egi and rewrote each per-block .raw "
                    "as one BIDS-EEG run. The per-block paradigm mapping "
                    "is NOT enumerated in Langer et al. 2017, so each "
                    "block is published as task-blockNN; the paradigm "
                    "sequence (Resting-state → Surround suppression → "
                    "Naturalistic viewing → Contrast change detection → "
                    "Sequence learning → Symbol search) is identical "
                    "across subjects per the paper but the mapping from "
                    "block index to paradigm should be confirmed against "
                    "the CMI MIPDB documentation. Source eye-tracking and "
                    "behavioural data are preserved in /sourcedata."
                ),
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
        "Version": "1.0.0",
    }


def parse_block_filename(fname: str) -> tuple[str, int] | None:
    """A00051826003.raw → ('A00051826', 3). Returns None if no match.

    MIPDB subject IDs are always A + 8 digits (e.g. A00051826), followed
    by a 3-digit block number. The strict length match avoids ambiguity:
    `A00051826.raw` (no block digits) correctly returns None rather than
    misparsing as subject `A00051` + block `826`.
    """
    m = re.match(r"(A\d{8})(\d{3})\.raw$", fname)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def convert_subject(
    src_dir: Path,
    sub_id: str,
    output_dir: Path,
    *,
    overwrite: bool = True,
    verbose: bool = False,
    copy_sourcedata: bool = True,
) -> tuple[int, int, int]:
    """Convert one MIPDB subject directory into the BIDS tree.

    Returns (n_runs_ok, n_runs_failed, n_skipped). n_skipped is 1 when
    the subject has no EEG/raw directory or no matching .raw files; 0
    otherwise. This distinguishes "processed but some runs failed" from
    "subject had no usable data at all".
    """
    raw_dir = src_dir / "EEG" / "raw" / "raw_format"
    if not raw_dir.exists():
        logger.warning("  %s: no EEG/raw/raw_format/, skipping", sub_id)
        return 0, 0, 1

    bids_sub = f"sub-{sub_id}"
    n_ok = 0
    n_fail = 0

    raw_files = sorted(p for p in raw_dir.glob(f"{sub_id}*.raw") if p.is_file())
    if not raw_files:
        logger.warning("  %s: no .raw files in raw_format/", sub_id)
        return 0, 0, 1

    for raw_path in raw_files:
        parsed = parse_block_filename(raw_path.name)
        if not parsed:
            continue
        _, block_idx = parsed
        task = task_for_index(block_idx)

        try:
            raw = mne.io.read_raw_egi(
                str(raw_path),
                preload=True,
                verbose=verbose,
            )
        except Exception:
            logger.exception("  %s task-%s: read failed", sub_id, task)
            n_fail += 1
            continue

        try:
            # Tag channel types: E1..E128 are scalp EEG on the EGI
            # HydroCel-128 net. E129 (if present) is the vertex reference
            # (Cz) — mark as misc to avoid validator confusion. The
            # remaining trailing numeric channels are EGI auxiliary
            # (event / sync) — also misc.
            eeg_picks = [
                c for c in raw.ch_names if re.fullmatch(r"E\d+", c) and c != "E129"
            ]
            misc_picks = [c for c in raw.ch_names if c not in eeg_picks]
            ch_type_map = {c: "eeg" for c in eeg_picks}
            ch_type_map.update({c: "misc" for c in misc_picks})
            raw.set_channel_types(ch_type_map, verbose=False)
            # Reference: EGI HydroCel uses Cz (vertex, electrode E129) as
            # the acquisition reference. We do not re-reference the data.

            # In modern MNE, read_raw_egi defaults to
            # events_as_annotations=True, so EGI DIN events are already
            # on raw.annotations. mne_bids picks them up and writes
            # events.tsv automatically.
            bids_path = mne_bids.BIDSPath(
                subject=sub_id,
                task=task,
                datatype="eeg",
                root=output_dir,
            )
            mne_bids.write_raw_bids(
                raw,
                bids_path,
                overwrite=overwrite,
                allow_preload=True,
                verbose=verbose,
                # BrainVision target — supported by NEMAR/BIDS-EEG
                format="BrainVision",
            )
            n_ok += 1
            logger.info(
                "  %s task-%s: %d ch, %.1fs",
                bids_sub,
                task,
                len(raw.ch_names),
                raw.times[-1],
            )
        except Exception:
            logger.exception("  %s task-%s: write failed", sub_id, task)
            n_fail += 1

    # Self-deposit eye-tracking + behavioral data into /sourcedata for
    # provenance (the eye-tracking format SMI .idf is not yet covered by
    # the BIDS-EyeTracking spec, so /sourcedata is the safe location).
    if copy_sourcedata:
        src_extras = {
            "Eyetracking": src_dir / "Eyetracking",
            "Behavioral": src_dir / "Behavioral",
        }
        for sub_subdir, src_path in src_extras.items():
            if not src_path.exists():
                continue
            dest = output_dir / "sourcedata" / bids_sub / sub_subdir
            if dest.exists():
                continue
            try:
                shutil.copytree(
                    src_path,
                    dest,
                    ignore=shutil.ignore_patterns(".DS_Store"),
                )
            except OSError:
                logger.exception(
                    "  %s: failed copying %s to /sourcedata",
                    sub_id,
                    sub_subdir,
                )

    return n_ok, n_fail, 0


def write_participants_tsv(output_dir: Path, subject_ids: list[str]) -> None:
    """Write a minimal participants.tsv (no per-subject demographics
    available without a phenotype mapping file).
    """
    rows = [
        {"participant_id": f"sub-{s}", "age": "n/a", "sex": "n/a", "hand": "n/a"}
        for s in subject_ids
    ]
    pd.DataFrame(rows).to_csv(output_dir / "participants.tsv", sep="\t", index=False)
    with open(output_dir / "participants.json", "w") as f:
        json.dump(
            {
                "participant_id": {
                    "Description": "Unique CMI subject identifier (A00…)"
                },
                "age": {
                    "Description": "Age at recording (not in MIPDB public release; populate from CMI phenotype if available)",
                    "Units": "years",
                },
                "sex": {
                    "Description": "Self-reported sex",
                    "Levels": {"M": "male", "F": "female", "n/a": "unknown"},
                },
                "hand": {
                    "Description": "Self-reported handedness",
                    "Levels": {
                        "R": "right",
                        "L": "left",
                        "A": "ambidextrous",
                        "n/a": "unknown",
                    },
                },
            },
            f,
            indent=2,
        )
        f.write("\n")


def convert_mipdb(
    input_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
    subjects: list[str] | None = None,
    skip_sourcedata: bool = False,
):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    # Discover subject directories
    all_subs = sorted(
        d.name for d in input_dir.iterdir() if d.is_dir() and re.match(r"A\d+", d.name)
    )
    target_subs = subjects if subjects else all_subs

    logger.info(
        "Found %d MIPDB subjects (processing %d)", len(all_subs), len(target_subs)
    )

    if dry_run:
        for s in target_subs:
            sub_dir = input_dir / s
            n = (
                len(list((sub_dir / "EEG" / "raw" / "raw_format").glob(f"{s}*.raw")))
                if (sub_dir / "EEG" / "raw" / "raw_format").exists()
                else 0
            )
            logger.info("[DRY] %s: %d .raw blocks", s, n)
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # dataset_description first so mne_bids.write_raw_bids accepts the root
    with open(output_dir / "dataset_description.json", "w") as f:
        json.dump(build_dataset_description(), f, indent=2)
        f.write("\n")

    # Self-deposit conversion script for provenance
    code_dir = output_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    self_path = Path(globals().get("__file__", "")).resolve()
    if self_path.exists() and self_path.is_file():
        shutil.copy2(self_path, code_dir / self_path.name)

    # Describe /sourcedata contents (eye-tracking + behavioral) so users
    # don't have to reverse-engineer the SMI vendor format. BIDS-ET does
    # not currently cover SMI .idf files; /sourcedata is the BIDS-spec
    # designated location for raw vendor output.
    if not skip_sourcedata:
        srcdata_dir = output_dir / "sourcedata"
        srcdata_dir.mkdir(parents=True, exist_ok=True)
        (srcdata_dir / "README").write_text(
            "MIPDB /sourcedata\n"
            "=================\n\n"
            "Per-subject raw, non-BIDS-converted auxiliary data from the CMI\n"
            "MIPDB distribution.\n\n"
            "Layout:\n"
            "  sub-<ID>/Eyetracking/idf/*.idf   SensoMotoric Instruments (SMI)\n"
            "                                    proprietary binary event log.\n"
            "                                    Decode with BeGaze or\n"
            "                                    iViewX / PyGaze-SMI.\n"
            "  sub-<ID>/Eyetracking/txt/*.txt   SMI ASCII export of the same\n"
            "                                    session (samples + events).\n"
            "  sub-<ID>/Behavioral/             Task behavioural responses\n"
            "                                    (CSV / MAT) produced by the\n"
            "                                    CMI acquisition software.\n\n"
            "These streams are not included in the BIDS-EEG tree because:\n"
            "  (a) SMI .idf is not a BIDS-EyeTracking supported format, and\n"
            "  (b) the behavioural CSV layouts are task-specific and lack a\n"
            "      published column dictionary.\n\n"
            "Upstream reference:\n"
            "  Langer N et al. 2017, Sci Data 4:170040 "
            "(doi:10.1038/sdata.2017.40)\n"
            "  https://fcon_1000.projects.nitrc.org/indi/cmi_eeg/\n"
        )

    n_ok_total = 0
    n_fail_total = 0
    n_skipped_total = 0
    written_subs: list[str] = []
    for s in target_subs:
        sub_dir = input_dir / s
        if not sub_dir.exists():
            logger.warning("Missing subject dir: %s", s)
            n_skipped_total += 1
            continue
        ok, fail, skipped = convert_subject(
            sub_dir,
            s,
            output_dir,
            overwrite=overwrite,
            verbose=verbose,
            copy_sourcedata=not skip_sourcedata,
        )
        n_ok_total += ok
        n_fail_total += fail
        n_skipped_total += skipped
        if ok > 0:
            written_subs.append(s)

    # Write participants.tsv LAST, based on actually-written subjects so
    # the file matches the sub-*/ directories on disk (BIDS validator
    # rejects participant rows with no corresponding subject dir).
    write_participants_tsv(output_dir, written_subs)

    logger.info(
        "Done: %d runs ok, %d failed, %d subjects skipped (no data)",
        n_ok_total,
        n_fail_total,
        n_skipped_total,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert CMI MIPDB EEG to BIDS-EEG (BrainVision)",
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
        default=None,
        help="Only process these subject IDs (A00…). Default: all.",
    )
    parser.add_argument(
        "--skip-sourcedata",
        action="store_true",
        help="Skip copying Eyetracking/Behavioral into /sourcedata.",
    )
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
    convert_mipdb(
        args.input,
        args.output,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
        subjects=args.subjects,
        skip_sourcedata=args.skip_sourcedata,
    )


if __name__ == "__main__":
    main()
