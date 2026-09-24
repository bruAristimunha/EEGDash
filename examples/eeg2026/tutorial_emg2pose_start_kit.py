"""EMG-to-pose with a real BIDS recording and the EEGDash viewer
====================================================================

**Difficulty 2** | **Runtime: about 2 min on first run** | **Compute: CPU**

The 2026 EMG-to-pose task maps a wearable surface-EMG recording to dense hand
joint-angle trajectories. The benchmark protects users, movement stages, and
their combinations while measuring angular error on held-out trajectories.

This lesson makes the data contract tangible with one small, real recording
from the `Salter2024 EMG2Pose BIDS release <https://nemar.org/dataexplorer/detail?dataset_id=NM000281>`_.
It downloads a 26.9-second, 16-channel EMG record with its 20 tracked joint
channels, identifies a genuine five-second clean span, and opens the native
EEGDash trace viewer.

EEGDash owns this BIDS acquisition and signal audit. NeuralBench owns the
paper split, model fitting, angular-error metric, and submission workflow.

Can the recorded EMG, joint channels, and valid time span support the exact
five-second trajectory interface used by the benchmark?

Keywords: EEG2026, EMG, hand pose, BIDS, EEGDash viewer, NeuralBench
"""

# %% [markdown]
# Learning objectives
# -------------------
#
# After this tutorial, you will be able to:
#
# - Materialize one compact, real EMG2Pose BIDS record with
#   :class:`eegdash.EEGDashDataset`.
# - Use BIDS channel metadata to separate its 16 EMG channels from 20 recorded
#   joint-angle channels.
# - Derive a complete five-second span while excluding any ``BAD_IK`` label and
#   the padded BDF tail.
# - Inspect real EMG and joint trajectories, then open the same BDF in the
#   inline EEGDash viewer.
# - Hand the full split, training, scoring, and submission work to NeuralBench
#   without recreating its benchmark in this data tutorial.

# %% [markdown]
# Requirements
# ------------
#
# - About two minutes on CPU the first time; the one BDF is about 5.8 MiB and
#   remains in the configured EEGDash cache afterwards.
# - Network access is needed once for NEMAR ``nm000281``.
# - Prerequisite: basic familiarity with continuous recordings and BIDS
#   sidecars.

# %%
# Setup
import matplotlib.pyplot as plt
import mne
import mne_bids
import numpy as np
import pandas as pd

from eegdash import EEGDashDataset
from eegdash.paths import get_default_cache_dir
from eegdash.viz import (
    EEGDASH_BLUE,
    EEGDASH_MINT,
    EEGDASH_ORANGE,
    EEGDASH_PURPLE,
    EEGDASH_SKY,
    style_figure,
    use_eegdash_style,
)

use_eegdash_style()
mne.set_log_level("ERROR")

DATASET = "nm000281"
SUBJECT = "04"
SESSION = "02"
RUN = "30"
EXPECTED_BIDS_RELPATH = (
    "sub-04/ses-02/emg/"
    "sub-04_ses-02_task-emg2pose_run-30_recording-left_emg.bdf"
)
WINDOW_SECONDS = 5.0
SAMPLING_FREQUENCY = 2000.0
CACHE_DIR = get_default_cache_dir()


# %% [markdown]
# Step 1. Download one real EMG-to-pose recording
# -------------------------------------------------
#
# We deliberately use only a single public BDF: participant ``sub-04``, session
# ``02``, run ``30``, and the left wristband recording. The BIDS record contains
# 16 surface-EMG channels and 20 tracked hand-joint channels at 2 kHz. This is
# enough to audit the benchmark interface without downloading the full release.

# %%
dataset = EEGDashDataset(
    cache_dir=CACHE_DIR,
    dataset=DATASET,
    subject=SUBJECT,
    session=SESSION,
    run=RUN,
    task="emg2pose",
    download=True,
    n_jobs=1,
)
dataset.download_all(n_jobs=1)

assert len(dataset.records) == 1, "The fixed query must resolve to one BIDS record."
record = dataset.records[0]
assert record["bids_relpath"] == EXPECTED_BIDS_RELPATH

recording_path = dataset.data_dir / record["bids_relpath"]
assert recording_path.is_file(), f"Missing downloaded BDF: {recording_path}"

# MNE-BIDS reads the real channels.tsv sidecar, so channel types and radians
# are retained rather than inferred from the BDF's generic physical unit.
bids_path = mne_bids.get_bids_path_from_fname(recording_path, check=False)
raw = mne_bids.read_raw_bids(bids_path, verbose="ERROR")
sfreq = float(raw.info["sfreq"])
emg_picks = mne.pick_types(raw.info, emg=True, exclude=[])
joint_picks = mne.pick_types(raw.info, misc=True, exclude=[])

assert sfreq == SAMPLING_FREQUENCY
assert len(emg_picks) == 16, f"Expected 16 EMG channels, found {len(emg_picks)}."
assert len(joint_picks) == 20, f"Expected 20 joint channels, found {len(joint_picks)}."

# EEGDash's record metadata preserves the BIDS recording length before BDF
# padding. The file itself is slightly longer than this real acquisition.
valid_duration_s = float(record["ntimes"]) / float(record["sampling_frequency"])
assert raw.n_times >= int(round(valid_duration_s * sfreq))

manifest = pd.DataFrame(
    [
        {
            "BIDS recording": record["bids_relpath"],
            "real duration (s)": valid_duration_s,
            "BDF samples": raw.n_times,
            "sample rate (Hz)": sfreq,
            "EMG channels": len(emg_picks),
            "joint channels": len(joint_picks),
        }
    ]
).round({"real duration (s)": 3, "sample rate (Hz)": 0})
manifest

# %% [markdown]
# **Investigate.** The BDF has 54,000 samples because its last data record is
# padded. The BIDS duration carried by EEGDash is 26.933 seconds, so it sets
# the valid upper boundary for every window below.

# %% [markdown]
# Step 2. Select a valid five-second trajectory window
# ------------------------------------------------------
#
# The full NeuralBench task removes ``BAD_IK`` spans, which mark failed
# inverse-kinematics labels, and drops windows that reach the padded tail. This
# fixed record has no ``BAD_IK`` span, but the selection rule is still applied
# to its real BDF annotations instead of assuming that fact.

# %%
def first_valid_window_start(raw, valid_duration):
    """Return the first complete five-second span outside BAD_IK annotations."""
    bad_spans = []
    for onset, duration, description in zip(
        raw.annotations.onset,
        raw.annotations.duration,
        raw.annotations.description,
        strict=True,
    ):
        if str(description) == "BAD_IK":
            start = max(float(onset), 0.0)
            stop = min(float(onset) + float(duration), valid_duration)
            if stop > start:
                bad_spans.append((start, stop))

    cursor = 0.0
    for start, stop in sorted(bad_spans):
        if start - cursor >= WINDOW_SECONDS:
            return cursor
        cursor = max(cursor, stop)
    if valid_duration - cursor >= WINDOW_SECONDS:
        return cursor
    raise ValueError(
        f"{EXPECTED_BIDS_RELPATH} has no clean {WINDOW_SECONDS}-second window."
    )


window_start_s = first_valid_window_start(raw, valid_duration_s)
window_samples = int(round(WINDOW_SECONDS * sfreq))
start_sample = int(round(window_start_s * sfreq))
stop_sample = start_sample + window_samples
valid_samples = int(round(valid_duration_s * sfreq))

assert stop_sample <= valid_samples
assert window_samples == 10_000

emg_window = raw.get_data(picks=emg_picks, start=start_sample, stop=stop_sample)
joint_window = raw.get_data(
    picks=joint_picks, start=start_sample, stop=stop_sample
)
emg_names = [raw.ch_names[pick] for pick in emg_picks]
joint_names = [raw.ch_names[pick] for pick in joint_picks]
raw.close()

assert emg_window.shape == (16, window_samples)
assert joint_window.shape == (20, window_samples)

window_summary = pd.DataFrame(
    {
        "window start (s)": [window_start_s],
        "window duration (s)": [WINDOW_SECONDS],
        "EMG shape (channels, samples)": [emg_window.shape],
        "joint shape (channels, samples)": [joint_window.shape],
    }
)
window_summary

# %% [markdown]
# **Run.** The selected interval starts at the recording onset and stops before
# 5 seconds. Its 10,000 samples are the same 2 kHz × 5 second shape used by the
# task's non-overlapping trajectory windows.

# %% [markdown]
# Step 3. Inspect real surface-EMG traces
# ----------------------------------------
#
# These four channels are measured traces from the selected window. Their BIDS
# unit is volts, so this diagnostic displays microvolts for readability. It is
# neither a feature transform nor a model prediction.

# %%
time = window_start_s + np.arange(window_samples) / sfreq
emg_examples = np.linspace(0, len(emg_names) - 1, 4, dtype=int)

fig, axes = plt.subplots(4, 1, figsize=(10.5, 6.6), sharex=True)
style_figure(
    fig,
    title="Five seconds of recorded surface EMG",
    subtitle="Four evenly spaced channels from one real NM000281 BIDS window",
    source="NEMAR nm000281 / Salter2024 EMG2Pose; amplitude in µV.",
    grid_axis="x",
)
fig.subplots_adjust(top=0.76, bottom=0.18, hspace=0.20)

for axis, channel_index, color in zip(
    axes,
    emg_examples,
    (EEGDASH_BLUE, EEGDASH_SKY, EEGDASH_PURPLE, EEGDASH_ORANGE),
    strict=True,
):
    axis.plot(time, emg_window[channel_index] * 1e6, color=color, lw=0.65)
    axis.set(ylabel=f"{emg_names[channel_index]}\n(µV)")
axes[-1].set(xlabel="Seconds from recording start")
plt.show()

# %% [markdown]
# Step 4. Inspect the recorded joint-angle targets
# --------------------------------------------------
#
# The 20 ``MISC`` channels are the tracked joint angles accompanying the EMG.
# BIDS declares them in radians, which is the honest unit for this data view.
# NeuralBench owns the task-level target conversion and reports its final MAE
# in degrees; no such metric is calculated here.

# %%
joint_examples = np.linspace(0, len(joint_names) - 1, 5, dtype=int)

fig, axes = plt.subplots(5, 1, figsize=(10.5, 7.2), sharex=True)
style_figure(
    fig,
    title="Recorded hand-joint trajectories accompanying the EMG",
    subtitle="Five of 20 real BIDS joint-angle channels from the same window",
    source="NEMAR nm000281 / Salter2024 EMG2Pose; angles in radians, not predictions.",
    grid_axis="x",
)
fig.subplots_adjust(top=0.77, bottom=0.17, hspace=0.17)

for axis, channel_index, color in zip(
    axes,
    joint_examples,
    (EEGDASH_MINT, EEGDASH_BLUE, EEGDASH_PURPLE, EEGDASH_ORANGE, EEGDASH_SKY),
    strict=True,
):
    axis.plot(time, joint_window[channel_index], color=color, lw=1.0)
    axis.set(ylabel=f"{joint_names[channel_index]}\n(rad)")
axes[-1].set(xlabel="Seconds from recording start")
plt.show()

# %% [markdown]
# Step 5. Open the materialized BDF in the EEGDash viewer
# ---------------------------------------------------------
#
# ``EEGDashDataset.plot()`` packages the real BDF plus its BIDS channel and
# event sidecars into a local interactive trace viewer. Pan through the entire
# recording and inspect the channel metadata there. This record has no
# ``*_desc-pose.json`` sidecar, so the viewer shows the genuine trace interface
# without inventing a hand panel.

# %%
dataset.plot(index=0, height=520)

# %% [markdown]
# Result: hand the full benchmark to NeuralBench
# -----------------------------------------------
#
# EEGDash has now provided a real BIDS record, its channel roles, a valid
# five-second EMG/trajectory pair, two signal diagnostics, and an interactive
# viewer. The full predefined split additionally joins
# ``sourcedata/emg2pose_metadata.csv``; that release-level table is not
# materialized by a one-record download, so this lesson does not claim to run
# the paper split or produce a score.
#
# The corresponding NeuralBench implementation is currently the pinned
# ``emg-pose-neuralbench`` revision ``5fd0c89``. It owns the split,
# preprocessing, model, MAE, and submission machinery:
#
# .. code-block:: bash
#
#    neuralbench emg pose -m neuropose
