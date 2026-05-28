#!/usr/bin/env python3
from __future__ import annotations

"""Convert the Nieuwland et al. 2018 multi-site N400 replication to BIDS-EEG.

"Large-scale replication study reveals a limit on probabilistic prediction in
language comprehension" — 356 subjects from 9 UK laboratories read sentences
word-by-word (RSVP) to test phonological predictions on indefinite articles
(a/an) preceding expected vs unexpected nouns (DeLong et al. 2005 replication).

PRINCIPLE: include ALL subjects with available raw data (no blanket exclusions).
Quality flags are added to participants.tsv so users can filter themselves.

9 laboratories:
  BIRM  Birmingham        BrainVision 500 Hz     64 EEG
  BRIS  Bristol           BrainVision 1000 Hz    32 EEG (2 runs: main + control)
  EDIN  Edinburgh         BioSemi BDF 512 Hz     64 EEG + 8 EXG
  GLAS  Glasgow           BioSemi BDF 512 Hz     128 EEG + 8 EXG (biosemi128)
  KENT  Kent              BrainVision 500 Hz     64 EEG + HEOG/VEOG + A1/A2
  LOND  University Coll.  BioSemi BDF 512 Hz     32 EEG + 8 EXG (biosemi32)
  OXFO  Oxford            BioSemi BDF 2048 Hz    64 EEG + 8 EXG (+ 3 BV subjects)
  STIR  Stirling          Neuroscan CNT 250 Hz   64 EEG + EOG (custom reader)
  YORK  York              BrainVision 500 Hz     64 EEG + HEOG/VEOG

Subjects: ~356 total. All participants right-handed, native English speakers,
18-35 years (mean 19.8), 222 women / 134 men. 89 reported left-handed family.

Usage:
    python convert_nieuwland2018.py --input /tmp/nieuwland2018 --output /tmp/nieuwland2018_bids
    python convert_nieuwland2018.py --input /tmp/nieuwland2018 --output /tmp/nieuwland2018_bids --lab BIRM
    python convert_nieuwland2018.py --input /tmp/nieuwland2018 --output /tmp/nieuwland2018_bids --dry-run

Reference:
    Nieuwland, M.S., Politzer-Ahles, S., Heyselaar, E., Segaert, K., Darley, E.,
    Kazanina, N., ..., Huettig, F. (2018). Large-scale replication study
    reveals a limit on probabilistic prediction in language comprehension.
    eLife, 7, e33468. doi:10.7554/eLife.33468
    https://osf.io/eyzaq/
"""

import argparse
import csv
import json
import logging
import os
import re
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any

import mne
import mne_bids
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Lab order matching paper's Lab 1-9 numbering (from Figure 1 of paper)
LAB_NUMBER = {
    "BIRM": 1,
    "BRIS": 2,
    "EDIN": 3,
    "GLAS": 4,
    "KENT": 5,
    "LOND": 6,
    "OXFO": 7,
    "STIR": 8,
    "YORK": 9,
}

LAB_INSTITUTION = {
    "BIRM": "University of Birmingham",
    "BRIS": "University of Bristol",
    "EDIN": "University of Edinburgh",
    "GLAS": "University of Glasgow",
    "KENT": "University of Kent",
    "LOND": "University College London",
    "OXFO": "University of Oxford",
    "STIR": "University of Stirling",
    "YORK": "University of York",
}

LAB_INSTITUTION_ADDRESS = {
    "BIRM": "Edgbaston, Birmingham B15 2TT, United Kingdom",
    "BRIS": "Beacon House, Queens Road, Bristol BS8 1QU, United Kingdom",
    "EDIN": "Old College, South Bridge, Edinburgh EH8 9YL, United Kingdom",
    "GLAS": "University Avenue, Glasgow G12 8QQ, United Kingdom",
    "KENT": "Canterbury, Kent CT2 7NZ, United Kingdom",
    "LOND": "Gower Street, London WC1E 6BT, United Kingdom",
    "OXFO": "Wellington Square, Oxford OX1 2JD, United Kingdom",
    "STIR": "Stirling FK9 4LA, United Kingdom",
    "YORK": "Heslington, York YO10 5DD, United Kingdom",
}

LAB_HARDWARE = {
    "BIRM": ("Brain Products", "BrainVision actiCHamp"),
    "BRIS": ("Brain Products", "BrainVision actiCHamp"),
    "EDIN": ("BioSemi", "ActiveTwo"),
    "GLAS": ("BioSemi", "ActiveTwo"),
    "KENT": ("Brain Products", "BrainVision BrainAmp"),
    "LOND": ("BioSemi", "ActiveTwo"),
    "OXFO": ("BioSemi", "ActiveTwo"),
    "STIR": ("Neuroscan", "SynAmps"),
    "YORK": ("Brain Products", "BrainVision actiCHamp"),
}

# Trigger code mapping to BIDS trial_type labels
# From EEG_trigger_info.txt on OSF + NeuralSet reference
TRIGGER_MAP = {
    # Delong experiment: articles and nouns
    201: ("a_expected", "Article 'a', expected (high cloze)"),
    202: ("an_expected", "Article 'an', expected (high cloze)"),
    203: ("a_unexpected", "Article 'a', unexpected (low cloze)"),
    204: ("an_unexpected", "Article 'an', unexpected (low cloze)"),
    205: ("noun_expected", "Target noun, expected (high cloze)"),
    206: ("noun_unexpected", "Target noun, unexpected (low cloze)"),
    207: ("final_expected", "Sentence final word, expected condition"),
    208: ("final_unexpected", "Sentence final word, unexpected condition"),
    # Control experiment: a/an grammaticality
    210: ("control_correct", "Grammatically correct article (control exp)"),
    211: ("control_incorrect", "Grammatically incorrect article (control exp)"),
    # Fillers and markers
    212: ("filler_word", "Additional word marker (post-critical, variant 1)"),
    213: ("filler_word", "Additional word marker (post-critical, variant 2)"),
    250: ("question", "Comprehension question onset"),
    251: ("question", "Comprehension question onset (variant)"),
    255: ("filler_word", "Any other (non-critical) word"),
}

# Expected BIDS trial_type Levels for events.json
TRIAL_TYPE_LEVELS = {label: desc for label, desc in TRIGGER_MAP.values()}
TRIAL_TYPE_LEVELS.update(
    {
        "cloze_marker": "Cloze probability marker (trigger 1-100 or 200)",
        "item_marker": "Stimulus item marker (trigger 101-180)",
        "unknown_trigger": "Trigger not matched to any known category",
    }
)

# BDF-specific misc channels (BioSemi convention)
BDF_MISC_CHANNELS = [
    "EXG1",
    "EXG2",
    "EXG3",
    "EXG4",
    "EXG5",
    "EXG6",
    "EXG7",
    "EXG8",
    "GSR1",
    "GSR2",
    "Erg1",
    "Erg2",
    "Resp",
    "Plet",
    "Temp",
]

# Authors from the eLife paper (27 authors)
AUTHORS = [
    "Mante S. Nieuwland",
    "Stephen Politzer-Ahles",
    "Evelien Heyselaar",
    "Katrien Segaert",
    "Emily Darley",
    "Nina Kazanina",
    "Sarah Von Grebmer Zu Wolfsthurn",
    "Federica Bartolozzi",
    "Vita Kogan",
    "Aine Ito",
    "Diane Mézière",
    "Dale J. Barr",
    "Guillaume A. Rousselet",
    "Heather J. Ferguson",
    "Simon Busch-Moreno",
    "Xiao Fu",
    "Jyrki Tuomainen",
    "Eugenia Kulakova",
    "E. Matthew Husband",
    "David I. Donaldson",
    "Zdenko Kohút",
    "Shirley-Ann Rueschemeyer",
    "Falk Huettig",
]

# --------------------------------------------------------------------------
# Custom Neuroscan CNT reader (for STIR lab only)
# --------------------------------------------------------------------------


def read_neuroscan_cnt(fname: str | Path) -> mne.io.RawArray:
    """Read a Neuroscan CNT 3.0 file, working around MNE's n_samples bug.

    The STIR files have a corrupted total_samples field in the header
    (uninitialized memory). We compute the true number of samples from the
    event_table_pos offset or file size.
    """
    fname = str(fname)
    file_size = os.path.getsize(fname)

    with open(fname, "rb") as f:
        data_bytes = f.read()

    # Main header (900 bytes)
    if len(data_bytes) < 900:
        raise ValueError(f"{fname}: file too small to be a CNT file")

    version = data_bytes[:12].decode("ascii", errors="ignore").strip("\x00")
    if not version.startswith("Version"):
        raise ValueError(f"{fname}: not a Neuroscan CNT file (version={version!r})")

    nchannels = struct.unpack_from("<h", data_bytes, 370)[0]
    sfreq = struct.unpack_from("<h", data_bytes, 376)[0]
    # EventTablePos at offset 886 (int32, little-endian)
    event_table_pos = struct.unpack_from("<i", data_bytes, 886)[0]

    if nchannels <= 0 or nchannels > 512:
        raise ValueError(f"{fname}: invalid nchannels={nchannels}")
    if sfreq <= 0 or sfreq > 100_000:
        raise ValueError(f"{fname}: invalid sfreq={sfreq}")

    # Per-channel headers: 75 bytes each
    ch_header_size = 75
    channel_names: list[str] = []
    sensitivities: list[float] = []
    calibrations: list[float] = []
    for i in range(nchannels):
        off = 900 + i * ch_header_size
        name = (
            data_bytes[off : off + 10]
            .decode("ascii", errors="ignore")
            .strip("\x00")
            .strip()
        )
        if not name:
            name = f"ch{i + 1}"
        # Neuroscan: sensitivity at offset 47 (float32)
        sens = struct.unpack_from("<f", data_bytes, off + 47)[0]
        # Calibration at offset 59 (float32) — scales ADC to uV
        cal = struct.unpack_from("<f", data_bytes, off + 59)[0]
        channel_names.append(name)
        sensitivities.append(sens)
        calibrations.append(cal)

    data_start = 900 + nchannels * ch_header_size

    # Compute data end: prefer event_table_pos, fall back to file size
    if data_start < event_table_pos < file_size:
        data_end = event_table_pos
    else:
        data_end = file_size
    bytes_of_data = data_end - data_start
    sample_size = nchannels * 2  # int16 per channel
    n_samples = bytes_of_data // sample_size
    if n_samples <= 0:
        raise ValueError(f"{fname}: computed n_samples={n_samples}")

    # Read data as int16 little-endian, shape (n_samples, n_channels), transpose
    data_slice = data_bytes[data_start : data_start + n_samples * sample_size]
    arr = np.frombuffer(data_slice, dtype="<i2")
    arr = arr.reshape(n_samples, nchannels).T.astype(np.float64)

    # Apply Neuroscan calibration: uV = raw * sens * cal / 204.8
    # If sens/cal are zero (not populated), fall back to raw values in uV
    sens_arr = np.array(sensitivities, dtype=np.float64)
    cal_arr = np.array(calibrations, dtype=np.float64)
    if not np.all(sens_arr == 0) and not np.all(cal_arr == 0):
        scale = sens_arr * cal_arr / 204.8
        arr = arr * scale[:, None]
    # Convert uV → V for MNE
    arr = arr * 1e-6

    # Build channel types: EOG for VEO/HEO, misc for CB1/CB2, rest EEG
    ch_types: list[str] = []
    eog_names = {"VEO", "HEO", "VEOG", "HEOG"}
    misc_names = {"CB1", "CB2", "EKG", "ECG"}
    for name in channel_names:
        up = name.upper()
        if up in eog_names:
            ch_types.append("eog")
        elif up in misc_names:
            ch_types.append("misc")
        else:
            ch_types.append("eeg")

    info = mne.create_info(channel_names, float(sfreq), ch_types, verbose=False)
    raw = mne.io.RawArray(arr, info, verbose=False)

    # Parse events from event table if present
    if data_start < event_table_pos < file_size - 8:
        annots = _parse_neuroscan_events(
            data_bytes,
            event_table_pos,
            sfreq=float(sfreq),
            nchannels=nchannels,
        )
        if len(annots) > 0:
            raw.set_annotations(annots)

    return raw


def _parse_neuroscan_events(
    data_bytes: bytes,
    event_table_pos: int,
    sfreq: float,
    nchannels: int,
) -> mne.Annotations:
    """Parse Neuroscan event table.

    Event table format:
      1 byte teeg (event type: 1 or 2)
      4 bytes size (int32) — total size of events in bytes
      4 bytes offset (int32) — file offset (usually 0)
      Then N events follow.

    teeg == 1: 8-byte events (stim, keyboard, keypad, 4-byte byte_offset_in_data)
    teeg == 2: 19-byte events (stim, keyboard, keypad, 4-byte byte_offset_in_data, ...)

    Critically: the "offset" field in each event is a BYTE offset into the
    signal data (not a sample index). We divide by (nchannels * 2) to get
    the sample number.
    """
    if event_table_pos + 9 > len(data_bytes):
        return mne.Annotations([], [], [])
    teeg = data_bytes[event_table_pos]
    size = struct.unpack_from("<i", data_bytes, event_table_pos + 1)[0]

    if teeg not in (1, 2):
        return mne.Annotations([], [], [])

    event_size = 8 if teeg == 1 else 19
    n_events = size // event_size
    if n_events <= 0 or n_events > 100_000:
        return mne.Annotations([], [], [])

    event_start = event_table_pos + 9
    bytes_per_sample = nchannels * 2  # int16 per channel

    onsets: list[float] = []
    descriptions: list[str] = []
    for i in range(n_events):
        pos = event_start + i * event_size
        if pos + event_size > len(data_bytes):
            break
        stim = data_bytes[pos]  # uint8
        # Byte offset into signal data at byte 4 of the event record (uint32)
        byte_offset = struct.unpack_from("<I", data_bytes, pos + 4)[0]
        if stim == 0:
            continue
        sample_num = byte_offset // bytes_per_sample
        onset_sec = sample_num / sfreq
        if onset_sec < 0:
            continue
        onsets.append(onset_sec)
        descriptions.append(f"S  {stim}")

    return mne.Annotations(onsets, [0.0] * len(onsets), descriptions)


# --------------------------------------------------------------------------
# Lab-specific raw loaders
# --------------------------------------------------------------------------


def load_raw_bdf(
    fname: Path, lab: str, montage_name: str | None = None
) -> mne.io.BaseRaw:
    """Load a BioSemi BDF file with proper channel typing."""
    raw = mne.io.read_raw_bdf(
        str(fname),
        eog=["VEOG", "HEOG"],
        misc=BDF_MISC_CHANNELS,
        preload=False,
        verbose=False,
    )
    if montage_name is not None:
        try:
            montage = mne.channels.make_standard_montage(montage_name)
            raw.set_montage(montage, on_missing="ignore", verbose=False)
        except Exception as exc:
            logger.debug("Montage %s failed for %s: %s", montage_name, lab, exc)
    return raw


def load_raw_brainvision(
    fname: Path,
    lab: str,
    *,
    eog: list[str] | None = None,
    misc: list[str] | None = None,
) -> mne.io.BaseRaw:
    """Load a BrainVision file."""
    kwargs = {"preload": False, "verbose": False}
    if eog is not None:
        kwargs["eog"] = eog
    if misc is not None:
        kwargs["misc"] = misc
    raw = mne.io.read_raw_brainvision(str(fname), **kwargs)

    # KENT-specific: rename Af* → AF* to match standard montage
    if lab == "KENT":
        rename = {ch: ch.replace("Af", "AF") for ch in raw.ch_names if "Af" in ch}
        if rename:
            mne.rename_channels(raw.info, rename, verbose=False)

    # Apply standard 10-05 montage (BrainVision labs)
    try:
        montage = mne.channels.make_standard_montage("standard_1005")
        raw.set_montage(montage, on_missing="ignore", verbose=False)
    except Exception as exc:
        logger.debug("Montage standard_1005 failed for %s: %s", lab, exc)
    return raw


def load_raw_stir(fname: Path) -> mne.io.RawArray:
    """Load a STIR Neuroscan CNT file with custom reader."""
    raw = read_neuroscan_cnt(fname)
    # STIR channel names are uppercase; normalize common ones to match montage
    rename = {}
    for ch in raw.ch_names:
        up = ch.upper()
        # Capitalize: FP1→Fp1, FZ→Fz, etc., but keep full uppercase otherwise
        if up in {"FP1", "FP2", "FPZ"}:
            rename[ch] = up.capitalize().replace("Fp", "Fp")
        elif up in {"FZ", "CZ", "PZ", "OZ", "FCZ", "CPZ", "POZ"}:
            rename[ch] = up.capitalize()
    if rename:
        mne.rename_channels(raw.info, rename, verbose=False)
    try:
        montage = mne.channels.make_standard_montage("standard_1005")
        raw.set_montage(montage, on_missing="ignore", verbose=False)
    except Exception:
        pass
    return raw


# --------------------------------------------------------------------------
# Per-lab subject iteration
# --------------------------------------------------------------------------


def iter_subjects_birm(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate BIRM subjects. BrainVision files; VHDR was in nested zip (already extracted).

    Include ALL subjects 1-43, even those NeuralSet flagged as bad.
    """
    subjects = []
    for num in range(1, 44):
        sub_id = f"birm{num:02d}"
        vhdr = lab_dir / f"{sub_id}.vhdr"
        if not vhdr.exists():
            continue
        subjects.append((sub_id, {"vhdr": vhdr, "subject_num": num}))
    return subjects


def iter_subjects_bris(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate BRIS subjects. BrainVision, 2 tasks per subject (main + control)."""
    subjects = []
    for num in range(1, 40):
        sub_id = f"bris{num:02d}"
        main = lab_dir / f"{sub_id}_main.vhdr"
        control = lab_dir / f"{sub_id}_control.vhdr"
        files = {}
        if main.exists():
            files["main"] = main
        if control.exists():
            files["control"] = control
        if not files:
            continue
        subjects.append((sub_id, {"files": files, "subject_num": num}))
    return subjects


def iter_subjects_edin(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate EDIN subjects. BDF format."""
    subjects = []
    for num in range(1, 50):
        sub_id = f"edin{num}"
        bdf = lab_dir / f"{sub_id}.bdf"
        if not bdf.exists():
            continue
        subjects.append((sub_id, {"bdf": bdf, "subject_num": num}))
    return subjects


def iter_subjects_glas(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate GLAS subjects. BDF format (3-digit numbering), BioSemi 128."""
    subjects = []
    for num in range(1, 50):
        sub_id = f"glas{num:03d}"
        bdf = lab_dir / f"{sub_id}.bdf"
        if not bdf.exists():
            continue
        subjects.append((sub_id, {"bdf": bdf, "subject_num": num}))
    return subjects


def iter_subjects_kent(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate KENT subjects. BrainVision format (4-digit numbering)."""
    subjects = []
    for num in range(1, 50):
        sub_id = f"kent{num:04d}"
        vhdr = lab_dir / f"{sub_id}.vhdr"
        if not vhdr.exists():
            continue
        subjects.append((sub_id, {"vhdr": vhdr, "subject_num": num}))
    return subjects


def iter_subjects_lond(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate LOND subjects. BDF format. Subjects 1,2 have control runs.

    Some subjects have weird filenames with flag suffixes, e.g.:
      lond003(answered questions randomly).bdf
      lond004(possibly non native English speaker).bdf
    """
    subjects = []
    for num in range(1, 50):
        sub_id = f"lond{num:03d}"
        # Try plain filename first
        bdf = lab_dir / f"{sub_id}.bdf"
        flag = None
        if not bdf.exists():
            # Search for any file with flags in the name
            for f in lab_dir.glob(f"{sub_id}*.bdf"):
                if "_control" in f.name:
                    continue
                bdf = f
                # Extract flag from parentheses
                m = re.search(r"\(([^)]+)\)", f.name)
                if m:
                    flag = m.group(1)
                break
        if not bdf.exists():
            continue
        control = lab_dir / f"{sub_id}_control.bdf"
        files = {"main": bdf}
        if control.exists():
            files["control"] = control
        subjects.append((sub_id, {"files": files, "subject_num": num, "flag": flag}))
    return subjects


def iter_subjects_oxfo(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate OXFO subjects. Mostly BDF, 3 subjects in BrainVision."""
    subjects = []
    for num in range(1, 50):
        sub_id = f"oxfo{num}"
        bdf = lab_dir / f"{sub_id}.bdf"
        vhdr = lab_dir / f"{sub_id}.vhdr"
        files = {}
        if bdf.exists():
            files["main"] = ("bdf", bdf)
        elif vhdr.exists():
            files["main"] = ("vhdr", vhdr)
        else:
            continue
        subjects.append((sub_id, {"files": files, "subject_num": num}))
    return subjects


def iter_subjects_stir(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate STIR subjects. Neuroscan CNT format — custom reader required."""
    subjects = []
    for num in range(1, 50):
        # STIR files are named STIR1.cnt, STIR10.cnt, etc. (uppercase, no zero pad)
        sub_id = f"stir{num}"
        cnt = lab_dir / f"STIR{num}.cnt"
        if not cnt.exists():
            continue
        subjects.append((sub_id, {"cnt": cnt, "subject_num": num}))
    return subjects


def iter_subjects_york(lab_dir: Path) -> list[tuple[str, dict]]:
    """Iterate YORK subjects. BrainVision (vhdr/vmrk were in nested zips)."""
    subjects = []
    for num in range(1, 50):
        sub_id = f"york{num}"
        vhdr = lab_dir / f"YORK{num}.vhdr"
        if not vhdr.exists():
            continue
        subjects.append((sub_id, {"vhdr": vhdr, "subject_num": num}))
    return subjects


LAB_ITERATORS = {
    "BIRM": iter_subjects_birm,
    "BRIS": iter_subjects_bris,
    "EDIN": iter_subjects_edin,
    "GLAS": iter_subjects_glas,
    "KENT": iter_subjects_kent,
    "LOND": iter_subjects_lond,
    "OXFO": iter_subjects_oxfo,
    "STIR": iter_subjects_stir,
    "YORK": iter_subjects_york,
}


def load_raw_for_lab(lab: str, info: dict) -> dict[str, mne.io.BaseRaw]:
    """Dispatch to the correct raw reader for a given lab, return dict of {task: raw}.

    Most labs return {'delong': raw}. BRIS and LOND (subjects 1,2) can also
    return {'control': raw}.
    """
    out: dict[str, mne.io.BaseRaw] = {}

    if lab == "BIRM":
        raw = load_raw_brainvision(info["vhdr"], lab, eog=["EOG"], misc=["BIP1"])
        out["delong"] = raw
    elif lab == "BRIS":
        for task, vhdr in info["files"].items():
            raw = load_raw_brainvision(vhdr, lab)
            task_name = "delong" if task == "main" else "control"
            out[task_name] = raw
    elif lab == "EDIN":
        out["delong"] = load_raw_bdf(info["bdf"], lab, montage_name="biosemi64")
    elif lab == "GLAS":
        out["delong"] = load_raw_bdf(info["bdf"], lab, montage_name="biosemi128")
    elif lab == "KENT":
        out["delong"] = load_raw_brainvision(info["vhdr"], lab, eog=["HEOG", "VEOG"])
    elif lab == "LOND":
        for task, bdf in info["files"].items():
            raw = load_raw_bdf(bdf, lab, montage_name="biosemi32")
            task_name = "delong" if task == "main" else "control"
            out[task_name] = raw
    elif lab == "OXFO":
        kind, fname = info["files"]["main"]
        if kind == "bdf":
            raw = load_raw_bdf(fname, lab, montage_name="biosemi64")
        else:
            raw = load_raw_brainvision(fname, lab)
        out["delong"] = raw
    elif lab == "STIR":
        out["delong"] = load_raw_stir(info["cnt"])
    elif lab == "YORK":
        out["delong"] = load_raw_brainvision(
            info["vhdr"], lab, eog=["HEOG", "VEOG"], misc=["BIP1"]
        )
    else:
        raise ValueError(f"Unknown lab: {lab}")

    return out


# --------------------------------------------------------------------------
# Stimuli loading (REPLICATION_ITEMS.xlsx)
# --------------------------------------------------------------------------


def load_stimuli(stimuli_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load Delong and Control stimuli from REPLICATION_ITEMS.xlsx."""
    delong = pd.read_excel(stimuli_path, sheet_name="Delong_Replication")
    # Clean up Delong columns (handle pandas duplicate name suffixes)
    delong.columns = [
        "item_number",
        "sentence_context",
        "expected_article",
        "expected_cloze",
        "unexpected_article",
        "unexpected_cloze",
        "expected_noun",
        "expected_noun_norming",
        "unexpected_noun",
        "unexpected_noun_norming",
        "sentence_ending",
        "list1",
        "list2",
        "qtype",
        "answer",
        "question",
        "extra",
        "plausibility_expected_noun",
        "plausibility_unexpected_noun",
    ]
    delong["item_number"] = delong["item_number"].astype(int)

    control = pd.read_excel(stimuli_path, sheet_name="Control_experiment")
    control.columns = [
        "item_number",
        "sentence_context",
        "critical_word",
        "ending",
        "correct_sentence",
        "incorrect_sentence",
        "list1_item",
        "list2_item",
    ]
    control["item_number"] = control["item_number"].astype(int)
    return delong, control


def load_accuracies(acc_path: Path) -> dict[str, dict]:
    """Parse accuracies.txt keyed by normalized subject ID."""
    out: dict[str, dict] = {}
    acc_path = Path(acc_path)
    if not acc_path.exists():
        return out
    with open(acc_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            raw_sub = row["subject"].strip()
            if not raw_sub:
                continue
            # Normalize: glas001 → glas001; STIR12 → stir12; birm01 → birm01
            norm = raw_sub.lower()
            acc = row.get("accuracy", "").strip()
            try:
                acc_val: Any = float(acc) if acc else None
            except ValueError:
                acc_val = None
            lst = row.get("list", "").strip()
            try:
                lst_val: Any = int(lst) if lst else None
            except ValueError:
                lst_val = None
            out[norm] = {
                "lab": row["lab"].strip(),
                "accuracy": acc_val,
                "list": lst_val,
                "original_subject": raw_sub,
            }
    return out


def load_trial_counts(article_path: Path, noun_path: Path) -> dict[str, dict[str, int]]:
    """Count trials per subject from lmem data files."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"article": 0, "noun": 0})
    if article_path.exists():
        df = pd.read_csv(article_path, sep="\t")
        for sub, n in df.groupby("subject").size().items():
            counts[str(sub).lower()]["article"] = int(n)
    if noun_path.exists():
        df = pd.read_csv(noun_path, sep="\t")
        for sub, n in df.groupby("subject").size().items():
            counts[str(sub).lower()]["noun"] = int(n)
    return dict(counts)


# --------------------------------------------------------------------------
# Event parsing and enrichment
# --------------------------------------------------------------------------


def extract_triggers_from_raw(raw: mne.io.BaseRaw) -> list[tuple[float, int]]:
    """Return list of (onset_sec, trigger_code) from a raw recording.

    For BDF: find_events on Status channel.
    For BrainVision: parse raw.annotations descriptions.
    For custom Neuroscan: annotations are already set by our reader.
    """
    triggers: list[tuple[float, int]] = []

    # Try Status channel (BDF)
    if "Status" in raw.ch_names:
        try:
            events = mne.find_events(
                raw, stim_channel="Status", shortest_event=1, verbose=False
            )
            sfreq = raw.info["sfreq"]
            for onset_samp, _, code in events:
                triggers.append((onset_samp / sfreq, int(code)))
            if triggers:
                return triggers
        except Exception as exc:
            logger.debug("find_events on Status failed: %s", exc)

    # Fall back to annotations
    for annot in raw.annotations:
        desc = str(annot["description"]).strip()
        # BrainVision format: "Stimulus/S123" or "Comment/..." or "S  1"
        # Neuroscan format (our custom): "S  123"
        m = re.search(r"[Ss]\s*(\d+)", desc)
        if m:
            triggers.append((float(annot["onset"]), int(m.group(1))))
        else:
            # Try just "123" or "/123"
            m2 = re.search(r"(\d+)", desc)
            if m2:
                code = int(m2.group(1))
                if 0 < code < 256:
                    triggers.append((float(annot["onset"]), code))

    return triggers


def _normalize_lab_subject(lab: str, sub_id: str) -> str:
    """Normalize lab+subject to the key used in accuracies.txt lookups."""
    # accuracies uses lowercase IDs like birm01, glas001, stir12, york1
    return sub_id.lower()


def build_events_df(
    raw: mne.io.BaseRaw,
    triggers: list[tuple[float, int]],
    task: str,
    subject_list: int | None,
    delong_df: pd.DataFrame,
    control_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build an enriched events DataFrame with stimulus metadata per trial.

    Columns:
      onset, duration, sample, value, trial_type,
      sequence_id, item_number, list, task_type, condition,
      expected_article, unexpected_article, expected_noun, unexpected_noun,
      expected_cloze, unexpected_cloze,
      plausibility_expected, plausibility_unexpected,
      sentence_context, sentence_ending,
      has_question, question_text, question_answer
    """
    sfreq = raw.info["sfreq"]
    rows: list[dict] = []
    for onset, code in triggers:
        row = {
            "onset": onset,
            "duration": 0.0,
            "sample": int(round(onset * sfreq)),
            "value": code,
            "trial_type": _code_to_trial_type(code, task),
        }
        rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=["onset", "duration", "sample", "value", "trial_type"]
        )

    df = pd.DataFrame(rows)

    # Initialize enrichment columns
    enrich_cols = [
        "sequence_id",
        "item_number",
        "list",
        "task_type",
        "condition",
        "expected_article",
        "unexpected_article",
        "expected_noun",
        "unexpected_noun",
        "expected_cloze",
        "unexpected_cloze",
        "plausibility_expected",
        "plausibility_unexpected",
        "sentence_context",
        "sentence_ending",
        "has_question",
        "question_text",
        "question_answer",
    ]
    for col in enrich_cols:
        df[col] = pd.NA

    df["task_type"] = task

    # Assign sequence IDs based on item markers (triggers 101-180).
    # Each item marker starts a new sentence sequence.
    seq_id = -1
    current_item: int | None = None
    for i, row in df.iterrows():
        code = row["value"]
        if 101 <= code <= 180:
            seq_id += 1
            current_item = code - 100
        df.at[i, "sequence_id"] = seq_id if seq_id >= 0 else pd.NA
        if current_item is not None:
            df.at[i, "item_number"] = current_item

    # Enrich from stimuli lookup
    if task == "delong" and subject_list is not None:
        _enrich_delong(df, delong_df, subject_list)
    elif task == "control" and subject_list is not None:
        _enrich_control(df, control_df, subject_list)

    # Set word duration (200 ms for each word stimulus)
    word_mask = df["trial_type"].isin(
        [
            "a_expected",
            "an_expected",
            "a_unexpected",
            "an_unexpected",
            "noun_expected",
            "noun_unexpected",
            "final_expected",
            "final_unexpected",
            "control_correct",
            "control_incorrect",
            "filler_word",
        ]
    )
    df.loc[word_mask, "duration"] = 0.200

    return df


def _code_to_trial_type(code: int, task: str) -> str:
    if code in TRIGGER_MAP:
        return TRIGGER_MAP[code][0]
    if 1 <= code <= 100 or code == 200:
        return "cloze_marker"
    if 101 <= code <= 180:
        return "item_marker"
    return "unknown_trigger"


def _enrich_delong(df: pd.DataFrame, delong: pd.DataFrame, subject_list: int) -> None:
    """Attach Delong stimuli metadata to events based on item_number."""
    # For each sentence sequence, look up item and compute expected/unexpected
    for item_num, group in df.groupby("item_number"):
        if pd.isna(item_num):
            continue
        try:
            item_num_i = int(item_num)
        except (ValueError, TypeError):
            continue
        match = delong.query("item_number == @item_num_i")
        if len(match) == 0:
            continue
        rec = match.iloc[0]
        idx = group.index

        df.loc[idx, "expected_article"] = rec["expected_article"]
        df.loc[idx, "unexpected_article"] = rec["unexpected_article"]
        df.loc[idx, "expected_noun"] = rec["expected_noun"]
        df.loc[idx, "unexpected_noun"] = rec["unexpected_noun"]
        df.loc[idx, "expected_cloze"] = rec["expected_cloze"]
        df.loc[idx, "unexpected_cloze"] = rec["unexpected_cloze"]
        df.loc[idx, "plausibility_expected"] = rec["plausibility_expected_noun"]
        df.loc[idx, "plausibility_unexpected"] = rec["plausibility_unexpected_noun"]
        df.loc[idx, "sentence_context"] = rec["sentence_context"]
        df.loc[idx, "sentence_ending"] = rec["sentence_ending"]
        df.loc[idx, "list"] = subject_list

        # Condition based on list assignment:
        #   list1 column says 'u' (unexpected) or 'e' (expected) for list 1
        #   list2 column says the complement for list 2
        list_key = "list1" if subject_list == 1 else "list2"
        condition = rec.get(list_key)
        if pd.notna(condition):
            df.loc[idx, "condition"] = (
                "expected" if str(condition).lower() == "e" else "unexpected"
            )

        # Questions
        if str(rec.get("qtype", "")).strip().upper() == "Q":
            df.loc[idx, "has_question"] = True
            df.loc[idx, "question_text"] = rec.get("question")
            answer = rec.get("answer")
            if pd.notna(answer):
                df.loc[idx, "question_answer"] = "yes" if int(answer) == 1 else "no"
        else:
            df.loc[idx, "has_question"] = False


def _enrich_control(df: pd.DataFrame, control: pd.DataFrame, subject_list: int) -> None:
    """Attach control stimuli metadata to events."""
    for item_num, group in df.groupby("item_number"):
        if pd.isna(item_num):
            continue
        try:
            item_num_i = int(item_num)
        except (ValueError, TypeError):
            continue
        match = control.query("item_number == @item_num_i")
        if len(match) == 0:
            continue
        rec = match.iloc[0]
        idx = group.index
        df.loc[idx, "sentence_context"] = rec["sentence_context"]
        df.loc[idx, "sentence_ending"] = rec["ending"]
        df.loc[idx, "list"] = subject_list
        # Which sentence was shown to this subject?
        shown = rec.get("list1_item") if subject_list == 1 else rec.get("list2_item")
        if pd.notna(shown):
            df.loc[idx, "sentence_context"] = shown


# --------------------------------------------------------------------------
# BIDS writers
# --------------------------------------------------------------------------


def write_dataset_description(bids_root: Path) -> None:
    desc = {
        "Name": "Nieuwland et al. 2018: Multi-site N400 Replication Study",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "CC-BY 4.0",
        "Authors": AUTHORS,
        "Acknowledgements": (
            "We thank all 356 participants and the research assistants at the "
            "9 participating laboratories. Ethical approval was obtained at "
            "each institution according to local guidelines."
        ),
        "Funding": [
            "Max Planck Society",
            "Economic and Social Research Council (ESRC) grants",
            "The Netherlands Organization for Scientific Research (NWO) Veni grant 275-89-021",
        ],
        "DatasetDOI": "doi:10.7554/eLife.33468",
        "ReferencesAndLinks": [
            "https://osf.io/eyzaq/",
            "https://doi.org/10.7554/eLife.33468",
            "https://elifesciences.org/articles/33468",
        ],
        "HowToAcknowledge": (
            "Please cite: Nieuwland, M.S., Politzer-Ahles, S., Heyselaar, E., "
            "Segaert, K., Darley, E., Kazanina, N., ..., Huettig, F. (2018). "
            "Large-scale replication study reveals a limit on probabilistic "
            "prediction in language comprehension. eLife, 7, e33468."
        ),
        "SourceDatasets": [{"URL": "https://osf.io/eyzaq/"}],
        "GeneratedBy": [
            {
                "Name": "convert_nieuwland2018.py (EEGDash)",
                "Description": (
                    "Converted from raw BDF/BrainVision/Neuroscan CNT files "
                    "from 9 laboratories to BIDS-EEG. Events enriched with "
                    "stimulus metadata from REPLICATION_ITEMS.xlsx."
                ),
                "CodeURL": "https://github.com/bruaristimunha/EEGDash",
            }
        ],
        "HEDVersion": "8.2.0",
    }
    with open(bids_root / "dataset_description.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_readme(bids_root: Path) -> None:
    readme = """\
Nieuwland et al. 2018: Multi-site N400 Replication Study
==========================================================

Overview
--------
This is a large-scale (N=356) multi-laboratory replication of DeLong, Urbach &
Kutas (2005), testing whether readers pre-activate the phonological form of
upcoming nouns during sentence comprehension. Participants read sentences
word-by-word (RSVP, 2 words per second) that contained indefinite articles
(a/an) preceding either highly expected or unexpected nouns (based on cloze
probability), while EEG was recorded.

Nine laboratories in the UK collected data following a pre-registered
replication protocol (https://osf.io/eyzaq). The original study by DeLong et
al. reported N400-like effects on the indefinite articles (larger negativity
for unexpected articles). Nieuwland et al. found reliable N400 effects on the
target nouns but no statistically significant effect on the preceding
articles, challenging strong prediction accounts.

Participants
------------
- 356 total participants (222 women / 134 men)
- All right-handed, native English speakers
- Age 18–35 years (mean 19.8)
- Normal or corrected-to-normal vision
- Free from known language or learning disorders
- 89 reported a left-handed parent or sibling

After applying the paper's quality threshold (<60/80 article or noun trials),
334 subjects were retained in the statistical analyses. In this BIDS release
we include ALL subjects for which raw data is available, with an
``included_in_paper`` flag in participants.tsv so users can filter themselves.

Laboratories
------------
| Lab (paper #) | Institution                | Format       | Sfreq    | Channels          |
|---------------|----------------------------|--------------|----------|-------------------|
| BIRM (1)      | University of Birmingham   | BrainVision  | 500 Hz   | 64 EEG            |
| BRIS (2)      | University of Bristol      | BrainVision  | 1000 Hz  | 32 EEG            |
| EDIN (3)      | University of Edinburgh    | BioSemi BDF  | 512 Hz   | 64 EEG + 8 EXG    |
| GLAS (4)      | University of Glasgow      | BioSemi BDF  | 512 Hz   | 128 EEG + 8 EXG   |
| KENT (5)      | University of Kent         | BrainVision  | 500 Hz   | 64 EEG + HEOG/VEOG|
| LOND (6)      | University College London  | BioSemi BDF  | 512 Hz   | 32 EEG + 8 EXG    |
| OXFO (7)      | University of Oxford       | BioSemi BDF  | 2048 Hz  | 64 EEG + 8 EXG    |
| STIR (8)      | University of Stirling     | Neuroscan CNT| 250 Hz   | 64 EEG + EOG      |
| YORK (9)      | University of York         | BrainVision  | 500 Hz   | 64 EEG + HEOG/VEOG|

Paradigm
--------
- Word-by-word RSVP: 200 ms word duration + 300 ms blank (2 words/sec)
- 80 Delong replication sentences + 80 control sentences
- Comprehension questions on a subset of trials (yes/no button response)
- Two counter-balanced stimulus lists (list 1 / list 2)

Tasks
-----
- ``task-delong``: Main experiment (all subjects, all labs)
- ``task-control``: Control grammaticality experiment (BRIS subjects, LOND 1-2)

Events (trial_type values)
--------------------------
Delong experiment:
  a_expected        — article "a", expected (high cloze) context
  an_expected       — article "an", expected (high cloze) context
  a_unexpected      — article "a", unexpected (low cloze) context
  an_unexpected     — article "an", unexpected (low cloze) context
  noun_expected     — target noun, expected condition
  noun_unexpected   — target noun, unexpected condition
  final_expected    — sentence-final word, expected condition
  final_unexpected  — sentence-final word, unexpected condition

Control experiment:
  control_correct   — grammatically correct article
  control_incorrect — grammatically incorrect article

General:
  cloze_marker      — cloze probability marker (trigger 1-100 or 200)
  item_marker       — stimulus item marker (trigger 101-180)
  question          — comprehension question onset
  filler_word       — any other (non-critical) word in sentence
  unknown_trigger   — trigger code not matched to any known category

Event enrichment
----------------
Each event in ``events.tsv`` is enriched (when applicable) with:
  - sequence_id, item_number, list, task_type, condition
  - expected_article / unexpected_article (a or an)
  - expected_noun / unexpected_noun (strings)
  - expected_cloze / unexpected_cloze (0-100)
  - plausibility_expected / plausibility_unexpected (1-7 Likert)
  - sentence_context / sentence_ending (strings)
  - has_question, question_text, question_answer

These come from the authors' REPLICATION_ITEMS.xlsx file on OSF.

participants.tsv columns
------------------------
  participant_id         — sub-<lab><num>
  lab                    — birm/bris/edin/glas/kent/lond/oxfo/stir/york
  lab_number             — 1-9 (paper's numbering)
  institution            — full institution name
  list                   — stimulus list (1 or 2)
  accuracy               — % correct on comprehension questions (from OSF)
  n_article_trials       — article trials kept (out of 80)
  n_noun_trials          — noun trials kept (out of 80)
  included_in_paper      — True if >=60/80 trials (paper's threshold)
  exclusion_note         — e.g. "random_answers", "non_native", "low_trials"
  hand                   — R (all right-handed)
  age_range              — 18-35 (all participants)
  native_language        — English (all participants)
  recording_system       — manufacturer + model

Notes
-----
- Original raw data is kept — no filtering, no resampling, no artifact rejection
- Channel types: EEG, EOG, and misc (peripheral) channels are labeled
- For BDF labs, channels EXG1-8, GSR1/2, Erg1/2, Resp, Plet, Temp are marked misc
- GLAS has a 128-channel BioSemi montage (biosemi128)
- STIR data is read with a custom Neuroscan CNT parser (MNE's built-in
  reader has a bug with the corrupted total_samples header field)
- OXFO has 3 subjects recorded with BrainVision instead of BDF

Reference
---------
Nieuwland, M.S., Politzer-Ahles, S., Heyselaar, E., Segaert, K., Darley, E.,
Kazanina, N., ..., Huettig, F. (2018). Large-scale replication study reveals
a limit on probabilistic prediction in language comprehension. eLife, 7,
e33468. https://doi.org/10.7554/eLife.33468
"""
    with open(bids_root / "README", "w") as f:
        f.write(readme)


def write_participants_json(bids_root: Path) -> None:
    desc = {
        "participant_id": {
            "Description": "Unique participant identifier (sub-<lab><num>)"
        },
        "lab": {
            "Description": "Laboratory code",
            "Levels": {
                "birm": "University of Birmingham (Lab 1)",
                "bris": "University of Bristol (Lab 2)",
                "edin": "University of Edinburgh (Lab 3)",
                "glas": "University of Glasgow (Lab 4)",
                "kent": "University of Kent (Lab 5)",
                "lond": "University College London (Lab 6)",
                "oxfo": "University of Oxford (Lab 7)",
                "stir": "University of Stirling (Lab 8)",
                "york": "University of York (Lab 9)",
            },
        },
        "lab_number": {"Description": "Paper's laboratory numbering (1-9)"},
        "institution": {"Description": "Full name of recording institution"},
        "list": {
            "Description": "Stimulus list assignment (counter-balanced)",
            "Levels": {"1": "List 1", "2": "List 2"},
        },
        "accuracy": {
            "Description": "Percentage correct on comprehension questions",
            "Units": "percent",
        },
        "n_article_trials": {
            "Description": "Number of article trials retained in authors' analysis (out of 80)",
        },
        "n_noun_trials": {
            "Description": "Number of noun trials retained in authors' analysis (out of 80)",
        },
        "included_in_paper": {
            "Description": (
                "True if the subject was included in the paper's N=334 analysis "
                "(at least 60 out of 80 trials for both articles and nouns)"
            ),
        },
        "exclusion_note": {
            "Description": (
                "Optional flag describing any issue noted by the authors or reference "
                "implementation (e.g. 'random_answers', 'non_native', 'low_trials')"
            ),
        },
        "hand": {
            "Description": "Handedness",
            "Levels": {"R": "Right-handed"},
        },
        "age_range": {
            "Description": "Age range across participants (18-35, mean 19.8)"
        },
        "native_language": {"Description": "Native language (all English)"},
        "recording_system": {"Description": "EEG amplifier manufacturer and model"},
    }
    with open(bids_root / "participants.json", "w") as f:
        json.dump(desc, f, indent=2)
        f.write("\n")


def write_events_json(events_json_path: Path) -> None:
    """Enrich events.json with Levels for trial_type and descriptions."""
    if not events_json_path.exists():
        return
    with open(events_json_path) as f:
        meta = json.load(f)

    meta["trial_type"] = {
        "Description": "Event type — see below for levels",
        "Levels": TRIAL_TYPE_LEVELS,
    }
    meta["value"] = {
        "Description": "Original integer trigger code from the recording",
    }
    meta["sequence_id"] = {
        "Description": "Sentence sequence index within the run (0-based)",
    }
    meta["item_number"] = {
        "Description": "Stimulus item number (1-80)",
    }
    meta["list"] = {
        "Description": "Stimulus list assignment (1 or 2)",
    }
    meta["task_type"] = {
        "Description": "Task type: delong or control",
    }
    meta["condition"] = {
        "Description": "Expected vs unexpected condition for this trial",
    }
    meta["expected_article"] = {
        "Description": "Indefinite article ('a' or 'an') that would be expected in the high-cloze condition",
    }
    meta["unexpected_article"] = {
        "Description": "Indefinite article that would be unexpected in the high-cloze condition",
    }
    meta["expected_noun"] = {
        "Description": "Target noun for the expected condition",
    }
    meta["unexpected_noun"] = {
        "Description": "Target noun for the unexpected condition",
    }
    meta["expected_cloze"] = {
        "Description": "Cloze probability for expected continuation (0-100)",
        "Units": "percent",
    }
    meta["unexpected_cloze"] = {
        "Description": "Cloze probability for unexpected continuation (0-100)",
        "Units": "percent",
    }
    meta["plausibility_expected"] = {
        "Description": "Mean plausibility rating of the expected noun (1-7 Likert)",
    }
    meta["plausibility_unexpected"] = {
        "Description": "Mean plausibility rating of the unexpected noun (1-7 Likert)",
    }
    meta["sentence_context"] = {
        "Description": "Leading sentence context (text before the critical article/noun)",
    }
    meta["sentence_ending"] = {
        "Description": "Sentence ending (text after the critical noun)",
    }
    meta["has_question"] = {
        "Description": "True if the sentence was followed by a comprehension question",
    }
    meta["question_text"] = {
        "Description": "Text of the comprehension question, if any",
    }
    meta["question_answer"] = {
        "Description": "Correct answer to the comprehension question",
        "Levels": {"yes": "Yes", "no": "No"},
    }
    meta["StimulusPresentation"] = {
        "OperatingSystem": "n/a",
        "SoftwareName": "E-Prime / Presentation",
        "SoftwareVersion": "n/a",
    }

    with open(events_json_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")


def _patch_coordsystem(eeg_dir: Path) -> None:
    """Add Fiducials* fields to coordsystem.json files.

    BIDS 1.9+ recommends both AnatomicalLandmark* and Fiducials* keys.
    MNE-BIDS only writes AnatomicalLandmark*, so we duplicate into Fiducials*.
    """
    for coord_path in Path(eeg_dir).glob("*_coordsystem.json"):
        with open(coord_path) as f:
            d = json.load(f)
        changed = False
        anat_coords = d.get("AnatomicalLandmarkCoordinates")
        anat_system = d.get("AnatomicalLandmarkCoordinateSystem")
        anat_units = d.get("AnatomicalLandmarkCoordinateUnits")
        eeg_desc = d.get("EEGCoordinateSystemDescription")

        if anat_coords and "FiducialsCoordinates" not in d:
            d["FiducialsCoordinates"] = anat_coords
            changed = True
        if anat_system and "FiducialsCoordinateSystem" not in d:
            d["FiducialsCoordinateSystem"] = anat_system
            changed = True
        if anat_units and "FiducialsCoordinateUnits" not in d:
            d["FiducialsCoordinateUnits"] = anat_units
            changed = True
        if eeg_desc and "FiducialsCoordinateSystemDescription" not in d:
            d["FiducialsCoordinateSystemDescription"] = (
                "Standard montage fiducials (NAS, LPA, RPA) from MNE's "
                "make_standard_montage. " + eeg_desc
            )
            changed = True
        if eeg_desc and "AnatomicalLandmarkCoordinateSystemDescription" not in d:
            d["AnatomicalLandmarkCoordinateSystemDescription"] = eeg_desc
            changed = True
        if changed:
            with open(coord_path, "w") as f:
                json.dump(d, f, indent=2)
                f.write("\n")


def enrich_eeg_sidecar(
    sidecar_path: Path, lab: str, subject_id: str, task: str
) -> None:
    """Enrich EEG sidecar JSON with lab-specific metadata."""
    if not sidecar_path.exists():
        return
    with open(sidecar_path) as f:
        sidecar = json.load(f)

    # BIDS spec requires MISCChannelCount (uppercase acronym).
    # MNE-BIDS writes MiscChannelCount (camelCase), so add the canonical one.
    if "MiscChannelCount" in sidecar and "MISCChannelCount" not in sidecar:
        sidecar["MISCChannelCount"] = sidecar["MiscChannelCount"]

    manufacturer, model = LAB_HARDWARE[lab]
    institution = LAB_INSTITUTION[lab]
    institution_addr = LAB_INSTITUTION_ADDRESS[lab]
    lab_num = LAB_NUMBER[lab]

    task_desc = (
        "Sentence reading (RSVP, 2 words/sec, 200 ms word duration + 300 ms blank). "
        "Subjects read sentences word-by-word while EEG was recorded. "
    )
    if task == "delong":
        task_desc += (
            "The main experiment (80 items) tested whether readers pre-activate "
            "upcoming words by examining N400-like responses to indefinite "
            "articles ('a' vs 'an') that precede expected or unexpected nouns."
        )
    else:
        task_desc += (
            "The control experiment (80 items) tested N400/P600 responses to "
            "grammatically correct vs incorrect indefinite articles."
        )

    sidecar.update(
        {
            "TaskName": task,
            "TaskDescription": task_desc,
            "Instructions": (
                "Read the sentences as they appear on screen and answer yes/no "
                "comprehension questions when they occur by pressing the button."
            ),
            "InstitutionName": institution,
            "InstitutionAddress": institution_addr,
            "InstitutionalDepartmentName": f"Lab {lab_num} ({lab})",
            "Manufacturer": manufacturer,
            "ManufacturersModelName": model,
            "CapManufacturer": "n/a",
            "CapManufacturersModelName": "n/a",
            "PowerLineFrequency": 50,
            "SoftwareFilters": "n/a",
            "HardwareFilters": "n/a",
            "SoftwareVersions": "n/a",
            "DeviceSerialNumber": "n/a",
            "RecordingType": "continuous",
            "SubjectArtefactDescription": "n/a",
            "CogAtlasID": "http://www.cognitiveatlas.org/task/id/trm_4f244f46d84cf",
            "CogPOID": "n/a",
            "EEGReference": _lab_reference(lab),
            "EEGPlacementScheme": _lab_placement(lab),
            "OriginalLabCode": lab,
        }
    )
    with open(sidecar_path, "w") as f:
        json.dump(sidecar, f, indent=2)
        f.write("\n")


def _lab_reference(lab: str) -> str:
    if lab in {"EDIN", "GLAS", "OXFO", "LOND"}:
        return "CMS/DRL (BioSemi active reference)"
    if lab == "KENT":
        return "Average of A1/A2 (mastoids)"
    return "As recorded (see original channels)"


def _lab_placement(lab: str) -> str:
    if lab == "GLAS":
        return "BioSemi ABCD 128-channel (biosemi128)"
    if lab == "LOND":
        return "BioSemi 32-channel (biosemi32)"
    if lab in {"EDIN", "OXFO"}:
        return "BioSemi 64-channel (biosemi64)"
    if lab == "STIR":
        return "Neuroscan 64-channel quik-cap"
    return "International 10-20/10-05 extended"


# --------------------------------------------------------------------------
# Main conversion
# --------------------------------------------------------------------------


def convert_subject(
    lab: str,
    sub_id: str,
    sub_info: dict,
    bids_root: Path,
    delong_df: pd.DataFrame,
    control_df: pd.DataFrame,
    accuracies: dict,
    trial_counts: dict,
    *,
    overwrite: bool,
    verbose: bool,
) -> tuple[int, dict | None]:
    """Convert a single subject, all tasks. Returns (n_tasks_ok, participants_row)."""
    bids_subject = sub_id  # lowercase lab-prefixed, e.g. "birm01"

    # Load raw data for this subject (may be multiple tasks)
    try:
        raws = load_raw_for_lab(lab, sub_info)
    except Exception as exc:
        logger.warning("FAILED load %s/%s: %s", lab, sub_id, exc)
        return 0, None

    if not raws:
        logger.warning("No raw data found for %s/%s", lab, sub_id)
        return 0, None

    # Get subject metadata from accuracies.txt
    acc_key = _normalize_lab_subject(lab, sub_id)
    acc = accuracies.get(acc_key, {})
    sub_list = acc.get("list")
    sub_accuracy = acc.get("accuracy")

    counts = trial_counts.get(acc_key, {"article": 0, "noun": 0})

    n_ok = 0
    for task, raw in raws.items():
        try:
            triggers = extract_triggers_from_raw(raw)
            events_df = build_events_df(
                raw, triggers, task, sub_list, delong_df, control_df
            )

            # Clean data: some subjects have Inf/NaN values in disconnected
            # channels (e.g. BIRM18 BIP1). Replace with 0 so pybv can write.
            raw.load_data(verbose=False)
            data = raw._data
            if np.any(~np.isfinite(data)):
                n_bad = int(np.sum(~np.isfinite(data)))
                logger.debug(
                    "  %s/%s (%s): replaced %d non-finite values with 0",
                    lab,
                    sub_id,
                    task,
                    n_bad,
                )
                data[~np.isfinite(data)] = 0.0

            # Convert events_df into mne.Annotations for write_raw_bids
            if len(events_df) > 0:
                # Only real events (skip unknown_trigger filler noise)
                onsets = events_df["onset"].astype(float).to_numpy()
                durations = events_df["duration"].astype(float).to_numpy()
                descriptions = events_df["trial_type"].astype(str).to_numpy()
                annots = mne.Annotations(
                    onsets, durations, descriptions, orig_time=None
                )
                raw.set_annotations(annots)

            # Write BIDS
            bids_path = mne_bids.BIDSPath(
                subject=bids_subject,
                task=task,
                datatype="eeg",
                root=bids_root,
            )
            mne_bids.write_raw_bids(
                raw,
                bids_path,
                overwrite=overwrite,
                verbose=verbose,
                allow_preload=True,
                format="BDF",
            )

            # Overwrite the events.tsv with our enriched version
            events_tsv = (
                bids_path.copy().update(suffix="events", extension=".tsv").fpath
            )
            if events_tsv.exists() and len(events_df) > 0:
                # Reorder columns so onset, duration come first (BIDS requirement)
                col_order = ["onset", "duration", "sample", "value", "trial_type"]
                for c in events_df.columns:
                    if c not in col_order:
                        col_order.append(c)
                events_df[col_order].to_csv(
                    events_tsv, sep="\t", index=False, na_rep="n/a"
                )

            # Enrich sidecars
            eeg_json = bids_path.copy().update(suffix="eeg", extension=".json").fpath
            enrich_eeg_sidecar(eeg_json, lab, bids_subject, task)

            events_json = (
                bids_path.copy().update(suffix="events", extension=".json").fpath
            )
            write_events_json(events_json)

            # Patch coordsystem.json to add Fiducials* fields (BIDS 1.9+)
            _patch_coordsystem(eeg_json.parent)

            n_ok += 1
        except Exception as exc:
            logger.warning("FAILED write %s/%s task=%s: %s", lab, sub_id, task, exc)
            continue

    if n_ok == 0:
        return 0, None

    # Build participants row
    n_art = counts["article"]
    n_noun = counts["noun"]
    included = (n_art >= 60) and (n_noun >= 60)

    exclusion_note = ""
    if not included and (n_art > 0 or n_noun > 0):
        exclusion_note = "low_trials"
    elif n_art == 0 and n_noun == 0:
        exclusion_note = "not_in_paper_analysis"
    if lab == "LOND" and sub_info.get("flag"):
        exclusion_note = sub_info["flag"][:40]

    manufacturer, model = LAB_HARDWARE[lab]
    row = {
        "participant_id": f"sub-{bids_subject}",
        "lab": lab.lower(),
        "lab_number": LAB_NUMBER[lab],
        "institution": LAB_INSTITUTION[lab],
        "list": sub_list if sub_list is not None else "n/a",
        "accuracy": sub_accuracy if sub_accuracy is not None else "n/a",
        "n_article_trials": n_art,
        "n_noun_trials": n_noun,
        "included_in_paper": included,
        "exclusion_note": exclusion_note or "n/a",
        "hand": "R",
        "age_range": "18-35",
        "native_language": "English",
        "recording_system": f"{manufacturer} {model}",
    }
    return n_ok, row


def convert_nieuwland2018(
    input_dir: Path,
    output_dir: Path,
    labs: list[str] | None = None,
    max_subjects: int | None = None,
    *,
    overwrite: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    raw_dir = input_dir / "raw"
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data directory not found: {raw_dir}")

    if labs is None:
        labs = list(LAB_ITERATORS.keys())

    # Load stimuli and metadata once
    stimuli_path = (
        input_dir
        / "stimuli"
        / "Stimuli"
        / "Sentence Materials"
        / "REPLICATION_ITEMS.xlsx"
    )
    if not stimuli_path.exists():
        raise FileNotFoundError(f"REPLICATION_ITEMS.xlsx not found at {stimuli_path}")
    delong_df, control_df = load_stimuli(stimuli_path)
    logger.info(
        "Loaded %d Delong items, %d control items", len(delong_df), len(control_df)
    )

    accuracies = load_accuracies(input_dir / "metadata" / "accuracies.txt")
    logger.info("Loaded accuracies for %d subjects", len(accuracies))

    trial_counts = load_trial_counts(
        input_dir / "metadata" / "public_article_data.txt",
        input_dir / "metadata" / "public_noun_data.txt",
    )
    logger.info("Loaded trial counts for %d subjects", len(trial_counts))

    # Enumerate subjects per lab
    lab_subjects: dict[str, list[tuple[str, dict]]] = {}
    total_subjects = 0
    for lab in labs:
        lab_dir = raw_dir / lab
        if not lab_dir.exists():
            logger.warning("Lab directory not found: %s", lab_dir)
            continue
        subs = LAB_ITERATORS[lab](lab_dir)
        lab_subjects[lab] = subs
        total_subjects += len(subs)
        logger.info("%s: %d subjects", lab, len(subs))

    if dry_run:
        print(f"Total subjects across {len(lab_subjects)} labs: {total_subjects}")
        for lab, subs in lab_subjects.items():
            print(f"  {lab}: {len(subs)}")
            for sub_id, info in subs[:3]:
                print(f"    - {sub_id}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    write_dataset_description(output_dir)
    write_readme(output_dir)
    write_participants_json(output_dir)

    all_participants: list[dict] = []
    total_ok = 0
    total_fail = 0

    processed = 0
    for lab, subs in lab_subjects.items():
        for sub_id, info in subs:
            if max_subjects is not None and processed >= max_subjects:
                break
            processed += 1
            n_tasks, p_row = convert_subject(
                lab,
                sub_id,
                info,
                output_dir,
                delong_df,
                control_df,
                accuracies,
                trial_counts,
                overwrite=overwrite,
                verbose=verbose,
            )
            if n_tasks > 0 and p_row is not None:
                all_participants.append(p_row)
                total_ok += 1
            else:
                total_fail += 1
            if processed % 10 == 0:
                logger.info(
                    "Progress: %d/%d subjects (%d ok, %d fail)",
                    processed,
                    total_subjects,
                    total_ok,
                    total_fail,
                )
        if max_subjects is not None and processed >= max_subjects:
            break

    # Write participants.tsv
    if all_participants:
        pdf = pd.DataFrame(all_participants)
        pdf.to_csv(output_dir / "participants.tsv", sep="\t", index=False, na_rep="n/a")

    logger.info("Done: %d ok, %d failed (of %d total)", total_ok, total_fail, processed)


def main():
    parser = argparse.ArgumentParser(
        description="Convert Nieuwland2018 multi-site N400 to BIDS",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, type=Path)
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument(
        "--lab",
        action="append",
        choices=list(LAB_ITERATORS.keys()),
        help="Limit to specific lab(s) (can be repeated)",
    )
    parser.add_argument(
        "--max-subjects",
        "-n",
        type=int,
        default=None,
        help="Max subjects to process (for testing)",
    )
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

    convert_nieuwland2018(
        args.input,
        args.output,
        labs=args.lab,
        max_subjects=args.max_subjects,
        overwrite=not args.no_overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
