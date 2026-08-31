"""EEG-to-image competition companion with one real NM000134 BIDS record
=========================================================================

**Difficulty 2** | **Runtime: 3–5 min on first run** | **Compute: CPU**

This competition companion inspects the genuine compact test-run recording
"nm000134/sub-09/ses-01/task-images/run-02". It materializes one 32-channel,
256 Hz EDF and parses the 936 "stim_test" BIDS rows that reference 200 real
image IDs. The event stream is deliberately fast, making it useful for
checking timing and stimulus coverage before building an EEG-to-image method.

This is a local alignment check, not an official train/test split, model,
score, or submission. NeuralBench owns those release-level operations.

Keywords: EEG2026, EEG-to-image, visual decoding, BIDS, NEMAR, EEGDash
"""

# %% [markdown]
# Learning objectives
# -------------------
#
# After this tutorial, you will be able to:
#
# - Materialize exactly one real NM000134 BIDS recording with EEGDashDataset.
# - Parse its "stim_test,<image_id>,..." event rows and audit their timing
#   and image-ID coverage.
# - Inspect a short, recorded EEG trace anchored to one real stimulus event.
# - Open the same EDF in EEGDash and inspect its BIDS stimulus mapping.
# - Hand official splits, models, scores, and submissions to NeuralBench.

# %% [markdown]
# Requirements
# ------------
#
# - About 3–5 minutes on CPU on the first run. The initial download's EDF,
#   BIDS sidecar, and event-referenced BIDS asset bytes are cached by EEGDash.
#   A rerun still needs catalog and hosted-viewer network access.
# - Prerequisite: basic familiarity with continuous EEG and BIDS events.

# %%
# Setup
import matplotlib.pyplot as plt
import mne
import numpy as np
import pandas as pd

from eegdash import EEGDashDataset
from eegdash.paths import get_default_cache_dir
from eegdash.viz import (
    EEGDASH_BLUE,
    EEGDASH_MINT,
    EEGDASH_ORANGE,
    EEGDASH_PURPLE,
    style_figure,
    use_eegdash_style,
)

use_eegdash_style()
mne.set_log_level("ERROR")

DATASET = "nm000134"
SUBJECT = "09"
SESSION = "01"
TASK = "images"
RUN = "02"
EXPECTED_BIDS_RELPATH = "sub-09/ses-01/eeg/sub-09_ses-01_task-images_run-02_eeg.edf"
EXPECTED_STIM_TEST_EVENTS = 936
EXPECTED_UNIQUE_IMAGE_IDS = 200
EXPECTED_EEG_CHANNELS = 32
SAMPLING_FREQUENCY = 256.0
TRACE_BEFORE_SECONDS = 0.25
TRACE_AFTER_SECONDS = 1.25
CACHE_DIR = get_default_cache_dir()
OFFICIAL_START_KIT_URL = "https://neural-interfaces26.github.io/startkit.html"


# %% [markdown]
# Orient: local alignment versus the official competition
# --------------------------------------------------------
#
# **Predict.** This page verifies that an event, its EEG epoch, and its BIDS
# stimulus agree. Track 01 predicts a ranked image retrieval result from one
# EEG epoch; it evaluates unseen stimuli with Top-5 retrieval accuracy.
#
# **Modify.** Do not turn this one-record check into a local benchmark: it has
# no score or split. The official workflow begins at
# `the NeuralBench start kit <https://neural-interfaces26.github.io/startkit.html>`_.

# %%
competition_map = pd.DataFrame(
    [
        {
            "Question": "What enters the workflow?",
            "EEGDash companion": "One real NM000134 BIDS recording",
            "Official Track 01": "One EEG epoch",
        },
        {
            "Question": "What is the outcome?",
            "EEGDash companion": "Verify event, epoch, and stimulus alignment",
            "Official Track 01": "Rank held-out candidate images from frozen DINOv2-giant embeddings",
        },
        {
            "Question": "What establishes performance?",
            "EEGDash companion": "No score or split",
            "Official Track 01": "unseen stimuli; Top-5 retrieval accuracy",
        },
    ]
)
competition_map


# %% [markdown]
# Step 1. Materialize one real BIDS test-run recording
# -----------------------------------------------------
#
# This fixed query is intentionally narrow: it selects only participant
# "sub-09", session "01", task "images", and run "02". It is a compact real
# recording for inspecting the BIDS interface, not a declaration of an
# official benchmark partition.

# %%
dataset = EEGDashDataset(
    cache_dir=CACHE_DIR,
    dataset=DATASET,
    subject=SUBJECT,
    session=SESSION,
    task=TASK,
    run=RUN,
    download=True,
    n_jobs=1,
)
dataset.download_all(n_jobs=1)

assert len(dataset.records) == 1, "The fixed query must resolve to one record."
record = dataset.records[0]
assert record["bids_relpath"] == EXPECTED_BIDS_RELPATH
assert float(record["sampling_frequency"]) == SAMPLING_FREQUENCY
assert int(record["nchans"]) == EXPECTED_EEG_CHANNELS

recording_path = dataset.data_dir / record["bids_relpath"]
events_path = recording_path.with_name(
    recording_path.name.replace("_eeg.edf", "_events.tsv")
)
assert recording_path.is_file(), f"Missing downloaded EDF: {recording_path}"
assert events_path.is_file(), f"Missing BIDS events: {events_path}"

raw = dataset.datasets[0].raw
assert raw is not None
sfreq = float(raw.info["sfreq"])
eeg_picks = mne.pick_types(raw.info, eeg=True, exclude=[])
recording_duration_s = raw.n_times / sfreq

assert sfreq == SAMPLING_FREQUENCY
assert len(eeg_picks) == EXPECTED_EEG_CHANNELS
assert raw.n_times >= int(record["ntimes"])

pd.DataFrame(
    [
        {
            "BIDS recording": record["bids_relpath"],
            "duration (s)": recording_duration_s,
            "samples": raw.n_times,
            "sample rate (Hz)": sfreq,
            "EEG channels": len(eeg_picks),
        }
    ]
).round({"duration (s)": 3, "sample rate (Hz)": 0})

# %% [markdown]
# **Run.** The record is a full 255-second EDF, not a fabricated
# excerpt. Its BIDS events sidecar supplies the image references used below.

# %% [markdown]
# Step 2. Parse the real image-event stream
# ------------------------------------------
#
# Each stimulus event encodes an image ID in "stim_test,<image_id>,...".
# We retain only those rows, convert their onset/sample values to numeric
# coordinates, and check the known event and image-ID totals directly from the
# downloaded sidecar.

# %%
events = pd.read_csv(events_path, sep="\t")
required_columns = {"onset", "duration", "trial_type", "sample"}
assert required_columns.issubset(events.columns), (
    f"{events_path} lacks required BIDS columns: {required_columns - set(events.columns)}"
)

stim_events = events.loc[
    events["trial_type"].astype(str).str.startswith("stim_test,")
].copy()
stim_events["onset"] = pd.to_numeric(stim_events["onset"], errors="raise")
stim_events["sample"] = pd.to_numeric(stim_events["sample"], errors="raise").astype(
    int
)
stim_events["image_id"] = stim_events["trial_type"].str.extract(
    r"^stim_test,(\d+),", expand=False
)
assert stim_events["image_id"].notna().all()
stim_events["image_id"] = pd.to_numeric(
    stim_events["image_id"], errors="raise"
).astype(int)

assert len(stim_events) == EXPECTED_STIM_TEST_EVENTS
assert stim_events["image_id"].nunique() == EXPECTED_UNIQUE_IMAGE_IDS
assert stim_events["image_id"].min() == 16540
assert stim_events["image_id"].max() == 16739

event_intervals_s = stim_events["onset"].sort_values().diff().dropna()
image_repeats = stim_events.groupby("image_id").size().sort_index()

pd.DataFrame(
    {
        "stimulus events": [len(stim_events)],
        "unique image IDs": [image_repeats.size],
        "median event interval (s)": [event_intervals_s.median()],
        "median repeats per image": [image_repeats.median()],
    }
).round({"median event interval (s)": 3, "median repeats per image": 1})

stim_events = stim_events.reset_index(drop=True)
usable_events = stim_events.loc[
    (stim_events["onset"] >= TRACE_BEFORE_SECONDS)
    & (stim_events["onset"] + TRACE_AFTER_SECONDS <= recording_duration_s)
]
assert not usable_events.empty
anchor_event = usable_events.iloc[0]
anchor_event_table = pd.DataFrame(
    [
        {
            "event order": int(anchor_event.name) + 1,
            "image ID": int(anchor_event["image_id"]),
            "onset (s)": float(anchor_event["onset"]),
            "BIDS sample": int(anchor_event["sample"]),
        }
    ]
).round({"onset (s)": 3})
anchor_event_table

# %% [markdown]
# Step 3. Investigate real event intervals and image repeats
# -----------------------------------------------------------
#
# **Investigate.** The table identifies the selected event used in the trace
# below. The left panel makes rapid presentation intervals and pauses readable;
# the right panel asks whether image IDs have comparable repeat counts.

# %%
interval_bins_s = np.arange(0, np.ceil(event_intervals_s.max()) + 0.1, 0.1)
repeat_counts = image_repeats.value_counts().sort_index()

fig, (interval_axis, repeat_axis) = plt.subplots(1, 2, figsize=(11, 4.3))
style_figure(
    fig,
    title="Real NM000134 stimulus intervals and image repeats",
    subtitle="936 BIDS stimulus events across 200 image IDs in one test-run EDF",
    source="NEMAR nm000134; quantities are parsed from this recording's events.tsv.",
    grid_axis="y",
)
fig.subplots_adjust(top=0.72, bottom=0.24, wspace=0.34)

interval_axis.hist(
    event_intervals_s.to_numpy(),
    bins=interval_bins_s,
    color=EEGDASH_BLUE,
    edgecolor="white",
)
interval_axis.axvline(event_intervals_s.median(), color=EEGDASH_ORANGE, linestyle="--")
interval_axis.set(xlabel="Seconds since previous stimulus", ylabel="Event intervals")

repeat_axis.bar(
    repeat_counts.index,
    repeat_counts.to_numpy(),
    color=EEGDASH_MINT,
    edgecolor="none",
)
repeat_axis.set(xlabel="Repeats per image ID", ylabel="Number of image IDs")
plt.show()

# %% [markdown]
# Step 4. Inspect a short EEG trace anchored to a real image event
# -----------------------------------------------------------------
#
# **Modify.** The trace uses the event in ``anchor_event_table``: its selected
# image ID, BIDS sample, and onset identify the same presentation. This is a
# signal check, not an embedding, target, or prediction. For display only, we
# median-center each displayed channel; the raw EDF remains unchanged and
# amplitudes remain in µV.

# %%
anchor_sample = int(anchor_event["sample"])
pre_samples = int(round(TRACE_BEFORE_SECONDS * sfreq))
post_samples = int(round(TRACE_AFTER_SECONDS * sfreq))
start_sample = anchor_sample - pre_samples
stop_sample = anchor_sample + post_samples
trace_picks = eeg_picks[:4]

assert start_sample >= 0
assert stop_sample <= raw.n_times
trace = raw.get_data(picks=trace_picks, start=start_sample, stop=stop_sample)
trace_time_s = np.arange(trace.shape[-1]) / sfreq - TRACE_BEFORE_SECONDS
trace_microvolts = trace * 1e6
trace_display_microvolts = trace_microvolts - np.nanmedian(
    trace_microvolts, axis=1, keepdims=True
)
trace_names = [raw.ch_names[pick] for pick in trace_picks]
spacing = max(
    float(np.nanpercentile(np.abs(trace_display_microvolts), 95)) * 2.6, 10.0
)

fig, axis = plt.subplots(figsize=(10.8, 4.6))
style_figure(
    fig,
    title="Recorded EEG around one real image event",
    subtitle=(
        f"image ID {int(anchor_event.image_id)} at "
        f"{float(anchor_event.onset):.3f} seconds in the BIDS event stream"
    ),
    source=(
        "Four EEG channels from the NM000134 EDF; median-centered for display; "
        "amplitudes shown in µV."
    ),
    grid_axis="x",
)
fig.subplots_adjust(top=0.72, bottom=0.22, left=0.15)

for channel_index, (channel_name, trace_channel, color) in enumerate(
    zip(
        trace_names,
        trace_display_microvolts,
        (EEGDASH_BLUE, EEGDASH_MINT, EEGDASH_PURPLE, EEGDASH_ORANGE),
        strict=True,
    )
):
    offset = (len(trace_names) - channel_index - 1) * spacing
    axis.plot(trace_time_s, trace_channel + offset, color=color, lw=0.75)
    axis.text(
        trace_time_s[0] - 0.02,
        offset,
        channel_name,
        ha="right",
        va="center",
        fontsize=8,
    )

axis.axvline(0, color="#475569", lw=1.0, linestyle="--", label="BIDS event")
axis.set(
    xlabel="Seconds relative to image-event sample",
    ylabel="Recorded EEG (µV; median-centered offset traces)",
    yticks=[],
)
axis.legend(frameon=False, loc="upper right")
plt.show()
raw.close()

# %% [markdown]
# Step 5. Inspect the EDF and its BIDS stimulus mapping in EEGDash
# -----------------------------------------------------------------
#
# **Verify.** The inline viewer opens the same real EDF and BIDS sidecars.
# Your task: find the selected event from ``anchor_event_table``, position the
# cursor/window there, and confirm that the rendered stimulus matches its BIDS
# image ID. The viewer materializes only event-referenced BIDS assets into the
# local cache and embeds them in the local viewer payload; it does not commit
# or substitute JPEGs. Fresh materialization is pinned to the 200 referenced
# image assets from the NM000134 BIDS v1.0.1 Git release, at immutable commit
# "61b04adf7bca47f220b85f3744a610b44046c62f", rather than a mutable HEAD
# branch. Pre-existing local BIDS stimulus files are intentionally reused.

# %%
dataset.plot(index=0, height=520)

# %% [markdown]
# Continue: move release-level benchmarking to NeuralBench
# ---------------------------------------------------------
#
# - [x] Local event, epoch, and viewer stimulus alignment checks are complete.
# - [x] No official score or split has been claimed from this record.
# - [ ] Run ``pip install neuralbench`` and follow the `official start kit <https://neural-interfaces26.github.io/startkit.html>`_ for official data, split, evaluation, and submission.
#
# NeuralBench—not this record—owns the official data, split, evaluation, and
# submission workflow.
