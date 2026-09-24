"""Sleep-onset prediction with a real Cassette EEG recording
=============================================================

**Difficulty 2** | **Runtime: about 2 min on first run** | **Compute: CPU**

The 2026 sleep-onset task asks a causal question: given a five-second EEG
window, how long remains until the first scored N2 sleep epoch? The target is
capped at ten minutes, and the benchmark balances errors across time-to-onset
bins rather than letting the many distant windows dominate the score.

This lesson uses the smallest exact-match record from the
`Sleep-EDF Cassette BIDS release <https://nemar.org/dataexplorer/detail?dataset_id=NM000185>`_:
one real, whole-night recording from ``sub-cassette59/ses-night2``. It reads
the BIDS sleep-stage annotations, finds the first N2 event, constructs the
same causal five-second windows, and opens the full recording in EEGDash.

EEGDash owns this BIDS acquisition and signal audit. NeuralBench owns the
subject-disjoint split, model fitting, binned MAE, and submission workflow.

Can the real BIDS recording and its N2 annotation support the task's causal
five-second interface without leaking future sleep-stage information?

Keywords: EEG2026, sleep onset, sleep staging, BIDS, EEGDash viewer, NeuralBench
"""

# %% [markdown]
# Learning objectives
# -------------------
#
# After this tutorial, you will be able to:
#
# - Materialize one real Sleep-EDF Cassette BIDS recording with
#   :class:`eegdash.EEGDashDataset`.
# - Identify the first scored N2 event from its BIDS ``events.tsv`` sidecar.
# - Form the exact causal five-second windows and capped time-to-N2 targets
#   used by the benchmark.
# - Inspect real sleep-stage annotations and recorded bipolar EEG excerpts.
# - Open the complete EDF in the inline EEGDash viewer, then hand the full
#   split, model, and score to NeuralBench.

# %% [markdown]
# Requirements
# ------------
#
# - About two minutes on CPU on the first run. The fixed 17-hour EDF is about
#   35.5 MiB and remains in the configured EEGDash cache afterwards.
# - Network access is needed once for NEMAR ``nm000185``.
# - Prerequisite: basic familiarity with continuous recordings, BIDS events,
#   and sleep stages.

# %%
# Setup
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
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

DATASET = "nm000185"
SUBJECT = "cassette59"
SESSION = "night2"
EXPECTED_BIDS_RELPATH = (
    "sub-cassette59/ses-night2/eeg/"
    "sub-cassette59_ses-night2_task-sleep_eeg.edf"
)
EEG_CHANNELS = ("EEG Fpz-Cz", "EEG Pz-Oz")
N2_LABEL = "N2"
EXPECTED_N2_ONSET_SECONDS = 32_070.0
WINDOW_SECONDS = 5.0
MAX_PRE_N2_SECONDS = 1200.0
TARGET_CAP_SECONDS = 600.0
BMAE_BIN_EDGES = (0.0, 40.0, 90.0, 300.0, 600.0)
CACHE_DIR = get_default_cache_dir()

STAGE_ORDER = ("Wake", "N1", "N2", "N3", "REM", "Unknown")
STAGE_COLORS = {
    "Wake": EEGDASH_ORANGE,
    "N1": EEGDASH_SKY,
    "N2": EEGDASH_BLUE,
    "N3": EEGDASH_PURPLE,
    "REM": EEGDASH_MINT,
    "Unknown": "#94A3B8",
}


# %% [markdown]
# Step 1. Download one exact-match Cassette recording
# ----------------------------------------------------
#
# The full NEMAR release has both Cassette and telemetry recordings. NeuralBench
# uses the 153-record Cassette cohort, so this tutorial deliberately selects
# ``sub-cassette59/ses-night2`` rather than a smaller telemetry record. It is a
# seven-channel, 100 Hz, whole-night EEG recording with scored BIDS sleep-stage
# events.

# %%
dataset = EEGDashDataset(
    cache_dir=CACHE_DIR,
    dataset=DATASET,
    subject=SUBJECT,
    session=SESSION,
    task="sleep",
    download=True,
    n_jobs=1,
)
dataset.download_all(n_jobs=1)

assert len(dataset.records) == 1, "The fixed query must resolve to one BIDS record."
record = dataset.records[0]
assert record["bids_relpath"] == EXPECTED_BIDS_RELPATH

recording_path = dataset.data_dir / record["bids_relpath"]
assert recording_path.is_file(), f"Missing downloaded EDF: {recording_path}"
events_path = recording_path.with_name(
    recording_path.name.replace("_eeg.edf", "_events.tsv")
)
assert events_path.is_file(), f"Missing BIDS events: {events_path}"

bids_path = mne_bids.get_bids_path_from_fname(recording_path, check=False)
raw = mne_bids.read_raw_bids(bids_path, verbose="ERROR")
sfreq = float(raw.info["sfreq"])
valid_duration_s = float(record["ntimes"]) / float(record["sampling_frequency"])
eeg_picks = mne.pick_channels(raw.ch_names, include=EEG_CHANNELS)

assert sfreq == 100.0
assert raw.n_times == int(round(valid_duration_s * sfreq))
assert len(raw.ch_names) == 7
assert len(eeg_picks) == len(EEG_CHANNELS)

manifest = pd.DataFrame(
    [
        {
            "BIDS recording": record["bids_relpath"],
            "duration (hours)": valid_duration_s / 3600,
            "samples": raw.n_times,
            "sample rate (Hz)": sfreq,
            "channels": len(raw.ch_names),
            "annotations": len(raw.annotations),
        }
    ]
).round({"duration (hours)": 1, "sample rate (Hz)": 0})
manifest

# %% [markdown]
# **Investigate.** This is an approximately 17-hour Cassette recording, not a
# cropped sample. Its BIDS sidecar carries the scored stage events that define
# the task boundary.

# %% [markdown]
# Step 2. Find the first scored N2 event and construct causal windows
# ---------------------------------------------------------------------
#
# NeuralBench finds the first scored N2 epoch, keeps at most the preceding 20
# minutes, and tiles that interval with non-overlapping five-second windows.
# A window's label is ``clip(first_N2 - window_stop, 0, 600)``: it depends on
# the end of the observed window, never on future EEG samples.

# %%
events = pd.read_csv(events_path, sep="\t")
events["onset"] = pd.to_numeric(events["onset"], errors="raise")
events["duration"] = pd.to_numeric(events["duration"], errors="raise")

n2_events = events.loc[events["trial_type"].eq(N2_LABEL)].sort_values("onset")
assert not n2_events.empty, "This record must contain a scored N2 event."
first_n2 = n2_events.iloc[0]
n2_onset_s = float(first_n2["onset"])
assert first_n2["original_stage"] == "Sleep stage 2"
assert n2_onset_s == EXPECTED_N2_ONSET_SECONDS
assert n2_onset_s <= valid_duration_s

pre_n2_start_s = max(0.0, n2_onset_s - MAX_PRE_N2_SECONDS)
window_starts_s = np.arange(
    pre_n2_start_s,
    n2_onset_s - WINDOW_SECONDS + 1e-9,
    WINDOW_SECONDS,
)
window_stops_s = window_starts_s + WINDOW_SECONDS
time_to_n2_s = np.clip(
    n2_onset_s - window_stops_s,
    0.0,
    TARGET_CAP_SECONDS,
)

assert window_stops_s[-1] == n2_onset_s
assert len(window_starts_s) == 240
assert time_to_n2_s[0] == TARGET_CAP_SECONDS
assert time_to_n2_s[-1] == 0.0

window_summary = pd.DataFrame(
    {
        "first N2 onset (s)": [n2_onset_s],
        "pre-N2 span (min)": [(n2_onset_s - pre_n2_start_s) / 60],
        "five-second windows": [len(window_starts_s)],
        "target range (s)": [f"{time_to_n2_s.min():.0f}–{time_to_n2_s.max():.0f}"],
    }
).round({"first N2 onset (s)": 0, "pre-N2 span (min)": 1})
window_summary

# %% [markdown]
# **Run.** The first N2 onset is at 32,070 seconds. The selected 20-minute
# pre-N2 interval produces 240 causal five-second windows; the final window
# ends at N2 and receives a target of zero seconds.

# %% [markdown]
# Step 3. Inspect the real scored sleep stages around the first N2 event
# -----------------------------------------------------------------------
#
# These are direct BIDS ``trial_type`` annotations, not stage predictions. The
# shaded portion is the exact 20-minute pre-N2 interval that supplies windows
# to the task; the vertical line marks the first event whose label is N2.

# %%
events["stop"] = events["onset"] + events["duration"]
context_stop_s = min(valid_duration_s, n2_onset_s + TARGET_CAP_SECONDS)
context_events = events.loc[
    (events["trial_type"].isin(STAGE_ORDER))
    & (events["stop"] > pre_n2_start_s)
    & (events["onset"] < context_stop_s)
]

fig, axis = plt.subplots(figsize=(11, 4.5))
style_figure(
    fig,
    title="Real scored sleep stages around the first N2 event",
    subtitle="Cassette59 night 2; time is relative to the first BIDS N2 annotation",
    source="NEMAR nm000185 / Sleep-EDF Cassette; BIDS events.tsv stage labels.",
    grid_axis="x",
)
fig.subplots_adjust(top=0.75, bottom=0.27)

axis.axvspan(
    (pre_n2_start_s - n2_onset_s) / 60,
    0,
    color="#E2E8F0",
    zorder=0,
    label="20-minute task span",
)
for event in context_events.itertuples(index=False):
    stage_index = STAGE_ORDER.index(event.trial_type)
    axis.broken_barh(
        [
            (
                (event.onset - n2_onset_s) / 60,
                event.duration / 60,
            )
        ],
        (stage_index - 0.38, 0.76),
        facecolors=STAGE_COLORS[event.trial_type],
        edgecolors="none",
    )
axis.axvline(0, color="#0F172A", lw=1.2, linestyle="--", label="first N2")
axis.set(
    xlim=(
        (pre_n2_start_s - n2_onset_s) / 60,
        (context_stop_s - n2_onset_s) / 60,
    ),
    yticks=range(len(STAGE_ORDER)),
    yticklabels=STAGE_ORDER,
    xlabel="Minutes relative to first N2 onset",
    ylabel="Scored BIDS stage",
)
stage_handles = [
    Patch(facecolor=STAGE_COLORS[stage], label=stage) for stage in STAGE_ORDER
]
task_handles = [
    Patch(facecolor="#E2E8F0", label="20-minute task span"),
    plt.Line2D([], [], color="#0F172A", lw=1.2, linestyle="--", label="first N2"),
]
axis.legend(
    handles=stage_handles + task_handles,
    ncol=4,
    frameon=False,
    loc="upper center",
    bbox_to_anchor=(0.5, -0.18),
    handlelength=1.3,
)
plt.show()

# %% [markdown]
# Step 4. Make the benchmark's target schedule visible
# ------------------------------------------------------
#
# The first part of the selected interval is more than ten minutes before N2,
# so its labels are capped at 600 seconds. NeuralBench reports binned MAE by
# ``[0, 40)``, ``[40, 90)``, ``[90, 300)``, and ``[300, 600]`` seconds, giving
# each non-empty bin equal weight. This is a target audit, not a prediction or
# a score.

# %%
bin_index = np.digitize(time_to_n2_s, BMAE_BIN_EDGES[1:-1], right=False)
bin_counts = np.bincount(bin_index, minlength=len(BMAE_BIN_EDGES) - 1)
bin_labels = ("[0, 40)", "[40, 90)", "[90, 300)", "[300, 600]")

fig, (target_axis, count_axis) = plt.subplots(1, 2, figsize=(11, 4.2))
style_figure(
    fig,
    title="Causal time-to-N2 targets from the real first N2 event",
    subtitle="Every point is one five-second window ending before the first N2 onset",
    source="Targets follow the NeuralBench sleep-onset rule; no model prediction shown.",
    grid_axis="y",
)
fig.subplots_adjust(top=0.72, bottom=0.26, wspace=0.36)

target_axis.step(
    (window_stops_s - n2_onset_s) / 60,
    time_to_n2_s,
    where="post",
    color=EEGDASH_BLUE,
    lw=1.5,
)
target_axis.axhline(
    TARGET_CAP_SECONDS,
    color=EEGDASH_ORANGE,
    lw=1.0,
    linestyle="--",
    label="600-second cap",
)
target_axis.set(
    xlabel="Minutes relative to first N2 onset",
    ylabel="Target: seconds remaining until N2",
    title="Window-end target",
)
target_axis.legend(frameon=False, loc="lower right")

bars = count_axis.bar(
    bin_labels,
    bin_counts,
    color=(EEGDASH_MINT, EEGDASH_SKY, EEGDASH_PURPLE, EEGDASH_ORANGE),
)
count_axis.bar_label(bars, padding=2, fontsize=8)
count_axis.set(
    xlabel="NeuralBench bMAE target bin (s)",
    ylabel="Real five-second windows",
    title="Windows available in each score bin",
)
plt.show()

# %% [markdown]
# Step 5. Inspect two real causal EEG windows
# ---------------------------------------------
#
# We inspect the two bipolar EEG channels explicitly referenced by the
# NeuralBench montage fallback. One real window ends ten minutes before N2 and
# receives the capped 600-second target; the other ends at the first N2 onset
# and receives zero. Neither window includes post-onset signal.

# %%
example_stops_s = (n2_onset_s - TARGET_CAP_SECONDS, n2_onset_s)
fig, axes = plt.subplots(1, len(example_stops_s), figsize=(11, 4.4), sharey=True)
style_figure(
    fig,
    title="Recorded five-second EEG windows at two causal task boundaries",
    subtitle="Fpz-Cz and Pz-Oz from the same real Cassette recording",
    source="Amplitude in µV; traces are vertically offset for readability.",
    grid_axis="x",
)
fig.subplots_adjust(top=0.72, bottom=0.25, wspace=0.26)

for axis, window_stop_s in zip(axes, example_stops_s, strict=True):
    start_sample = int(round((window_stop_s - WINDOW_SECONDS) * sfreq))
    stop_sample = int(round(window_stop_s * sfreq))
    window = raw.get_data(picks=eeg_picks, start=start_sample, stop=stop_sample)
    microvolts = window * 1e6
    time = np.arange(microvolts.shape[-1]) / sfreq - WINDOW_SECONDS
    spacing = max(float(np.nanpercentile(np.abs(microvolts), 95)) * 2.5, 20.0)
    for channel_index, (channel_name, color) in enumerate(
        zip(EEG_CHANNELS, (EEGDASH_BLUE, EEGDASH_PURPLE), strict=True)
    ):
        offset = (len(EEG_CHANNELS) - channel_index - 1) * spacing
        axis.plot(time, microvolts[channel_index] + offset, lw=0.8, color=color)
    target_s = float(
        np.clip(n2_onset_s - window_stop_s, 0.0, TARGET_CAP_SECONDS)
    )
    axis.axvline(0, color="#64748B", lw=0.8, linestyle="--")
    axis.set(
        title=f"Window target: {target_s:.0f} s",
        xlabel="Seconds before this window ends",
        yticks=[spacing, 0],
        yticklabels=EEG_CHANNELS,
    )
axes[0].set_ylabel("Recorded EEG (µV; offset traces)")
raw.close()
plt.show()

# %% [markdown]
# Step 6. Open the complete recording in the EEGDash viewer
# -----------------------------------------------------------
#
# ``EEGDashDataset.plot()`` packages the real whole-night EDF with its BIDS
# channel and event sidecars into a local interactive trace viewer. Pan to the
# first N2 event at about 8.9 hours, inspect its annotation, and compare it to
# the short static windows above.

# %%
dataset.plot(index=0, height=520)

# %% [markdown]
# Result: hand the full benchmark to NeuralBench
# -----------------------------------------------
#
# EEGDash has now provided an exact Cassette BIDS recording, its scored first
# N2 event, the causal 20-minute window selection, real EEG diagnostics, and
# an interactive viewer. It deliberately has not created a train/validation/
# test split or a prediction: the full NeuralBench task uses a subject-disjoint
# 60/20/20 split (seed 33), model fitting, and binned MAE across the four
# target ranges shown above.
#
# Run that benchmark in NeuralBench rather than duplicating it here:
#
# .. code-block:: bash
#
#    neuralbench eeg sleep_onset
