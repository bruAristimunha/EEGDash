"""EEG-to-BCI with a real cross-session BIDS dataset
======================================================

**Difficulty 2** | **Runtime: 3–5 min on first run** | **Compute: CPU**

The 2026 EEG-to-BCI track asks whether a decoder calibrated on a person's
early sessions can decode commands from their later sessions. The official
release contains motor imagery, calculation, and word-association commands;
its later sessions are held back for evaluation.

This lesson makes that workflow concrete with the small, real
`Zhou2016 BIDS release <https://nemar.org/dataexplorer/detail?dataset_id=NM000115>`_.
We download one participant's six EDF recordings (about 46.9 MiB), inspect
the BIDS event labels, and reserve the last session for later evaluation.
Zhou2016 has left-hand, right-hand, and feet motor-imagery commands, so it is
a transparent public proxy rather than the official 2026 dataset.

EEGDash handles the BIDS data and split audit in this tutorial. NeuralBench
handles target construction, model training, evaluation, and submissions.

Can the records, event labels, and session boundary support a trustworthy
cross-session BCI experiment?

Keywords: EEG2026, BCI, motor imagery, cross-session, BIDS, NeuralBench
"""

# %% [markdown]
# Learning objectives
# -------------------
#
# After this tutorial, you will be able to:
#
# - Materialize a small, real BIDS subset with :class:`eegdash.EEGDashDataset`.
# - Build and inspect a session-disjoint calibration/held-out manifest.
# - Read BIDS event rows and retain valid four-second motor-imagery windows.
# - Inspect real EEG windows and a simple session-level spectral diagnostic.
# - Hand the audited data boundary to NeuralBench without recreating its
#   benchmark or claiming a competition score.

# %% [markdown]
# Requirements
# ------------
#
# - About 3–5 minutes on CPU on the first run; the six EDF recordings are
#   cached in the EEGDash cache afterwards.
# - Network access is needed once to download NEMAR ``nm000115``.
# - Prerequisite: basic familiarity with BIDS sessions and runs.

# %%
# Setup
import matplotlib.pyplot as plt
import mne
import numpy as np
import pandas as pd
from mne.time_frequency import psd_array_welch

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

DATASET = "nm000115"
SUBJECT = "1"
SESSIONS = ("0", "1", "2")
CALIBRATION_SESSIONS = {"0", "1"}
HELD_OUT_SESSIONS = {"2"}
COMMANDS = ("left_hand", "right_hand", "feet")
WINDOW_SECONDS = 4.0
CACHE_DIR = get_default_cache_dir()

COMMAND_COLORS = {
    "left_hand": EEGDASH_BLUE,
    "right_hand": EEGDASH_PURPLE,
    "feet": EEGDASH_MINT,
}
SESSION_COLORS = {
    "0": EEGDASH_BLUE,
    "1": EEGDASH_SKY,
    "2": EEGDASH_ORANGE,
}

# %% [markdown]
# Step 1. Download one participant's real BIDS recordings
# ---------------------------------------------------------
#
# We deliberately keep this lesson small: participant ``sub-1``, three
# sessions, and two runs per session. Sessions 0 and 1 are labelled
# calibration data; session 2 stays outside any training decision. The same
# participant appears on both sides because this is a within-person,
# cross-session problem.

# %%
dataset = EEGDashDataset(
    cache_dir=CACHE_DIR,
    dataset=DATASET,
    subject=SUBJECT,
    session=list(SESSIONS),
    task="imagery",
    download=True,
    n_jobs=1,
)
dataset.download_all(n_jobs=1)

manifest_columns = (
    "data_name",
    "subject",
    "session",
    "run",
    "bids_relpath",
    "nchans",
    "ntimes",
    "sampling_frequency",
)
manifest = pd.DataFrame(dataset.records).loc[:, manifest_columns].copy()
manifest["subject"] = manifest["subject"].astype(str)
manifest["session"] = manifest["session"].astype(str)
manifest["run"] = manifest["run"].astype(str)
manifest["recording_duration_s"] = (
    manifest["ntimes"] / manifest["sampling_frequency"]
)
manifest["partition"] = np.where(
    manifest["session"].isin(CALIBRATION_SESSIONS), "calibration", "held out"
)
manifest = manifest.sort_values(
    ["session", "run"], key=lambda value: pd.to_numeric(value)
).reset_index(drop=True)

calibration = manifest.loc[manifest["partition"] == "calibration"]
held_out = manifest.loc[manifest["partition"] == "held out"]
assert len(manifest) == 6, f"Expected six records, found {len(manifest)}."
assert set(manifest["session"]) == set(SESSIONS)
assert (manifest.groupby("session")["run"].nunique() == 2).all()
assert len(calibration) == 4
assert len(held_out) == 2
assert set(calibration["session"]).isdisjoint(set(held_out["session"]))
assert set(calibration["subject"]) == set(held_out["subject"]) == {SUBJECT}

manifest.assign(recording_duration_min=manifest["recording_duration_s"] / 60)[
    ["session", "run", "partition", "recording_duration_min", "nchans"]
].round({"recording_duration_min": 1})

# %% [markdown]
# **Investigate.** The table is the split contract. It has four calibration
# recordings and two held-out recordings. The subject is intentionally shared;
# the session entity is what must not cross the boundary.

# %% [markdown]
# Step 2. Read the BIDS events and make valid EEG windows
# --------------------------------------------------------
#
# A BCI target comes from a BIDS event row, not from a guess based on the raw
# trace. We keep only the three observed command labels and require an event
# onset to leave a complete four-second window inside its recording.

# %%
event_rows = []
for record in manifest.itertuples(index=False):
    recording_path = dataset.data_dir / record.bids_relpath
    events_path = recording_path.with_name(
        recording_path.name.replace("_eeg.edf", "_events.tsv")
    )
    events = pd.read_csv(events_path, sep="\t")
    if "trial_type" not in events or "onset" not in events:
        raise ValueError(f"{events_path} lacks BIDS onset/trial_type columns.")

    events["onset"] = pd.to_numeric(events["onset"], errors="coerce")
    events["command"] = (
        events["trial_type"]
        .astype(str)
        .str.lower()
        .str.strip()
        .str.replace("-", "_", regex=False)
        .str.replace(" ", "_", regex=False)
    )
    valid = events.loc[
        events["command"].isin(COMMANDS)
        & events["onset"].notna()
        & (events["onset"] + WINDOW_SECONDS <= record.recording_duration_s)
    ].copy()
    valid["session"] = record.session
    valid["run"] = record.run
    valid["recording_path"] = str(recording_path)
    valid["partition"] = record.partition
    event_rows.append(valid)

event_table = pd.concat(event_rows, ignore_index=True)
assert not event_table.empty, "No valid four-second BIDS command windows found."
assert set(event_table["command"]) == set(COMMANDS)

event_counts = (
    event_table.groupby(["session", "command"])
    .size()
    .unstack(fill_value=0)
    .reindex(index=SESSIONS, columns=COMMANDS, fill_value=0)
)
event_counts

# %% [markdown]
# Step 3. Plot the recordings and observed command events
# --------------------------------------------------------
#
# **Run.** The left panel reports the real EDF durations. The right panel
# reports only event rows that can produce a full four-second window. It is a
# quick data check before any preprocessing or classifier is introduced.

# %%
fig, (duration_ax, event_ax) = plt.subplots(1, 2, figsize=(11, 4.2))
style_figure(
    fig,
    title="Real Zhou2016 recordings and command events",
    subtitle="One participant, three sessions, and six BIDS EDF recordings",
    source="NEMAR nm000115 / Zhou2016 materialized through EEGDash.",
    grid_axis="y",
)
fig.subplots_adjust(top=0.72, bottom=0.30, wspace=0.42)

record_labels = "ses-" + manifest["session"] + " / run-" + manifest["run"]
duration_ax.barh(
    record_labels,
    manifest["recording_duration_s"] / 60,
    color=[SESSION_COLORS[session] for session in manifest["session"]],
)
duration_ax.set(xlabel="Recording duration (min)", ylabel="")
duration_ax.set_title("Six materialized recordings", loc="left", fontweight="bold")

positions = np.arange(len(SESSIONS))
width = 0.23
for index, command in enumerate(COMMANDS):
    bars = event_ax.bar(
        positions + (index - 1) * width,
        event_counts[command].to_numpy(),
        width,
        label=command.replace("_", " "),
        color=COMMAND_COLORS[command],
    )
    event_ax.bar_label(bars, padding=2, fontsize=8)
event_ax.set(
    xticks=positions,
    xticklabels=[f"session {session}" for session in SESSIONS],
    ylabel="Valid four-second BIDS windows",
)
event_ax.set_title("Observed command events", loc="left", fontweight="bold")
event_ax.legend(
    frameon=False,
    loc="upper center",
    bbox_to_anchor=(0.5, -0.22),
    ncol=3,
    handlelength=1.5,
)
plt.show()

# %% [markdown]
# Step 4. Inspect three real event-anchored EEG windows
# ------------------------------------------------------
#
# **Investigate.** We read the first valid left-hand, right-hand, and feet
# event directly from the EDF recordings. These are raw amplitude excerpts,
# not model features and not a performance claim.

# %%
def load_event_window(event):
    """Return four seconds of recorded EEG beginning at one BIDS event."""
    raw = mne.io.read_raw_edf(event.recording_path, preload=False, verbose="ERROR")
    try:
        sfreq = float(raw.info["sfreq"])
        picks = mne.pick_types(raw.info, eeg=True, exclude=[])[:4]
        assert len(picks) == 4, "Expected at least four EEG channels."
        start = int(round(float(event.onset) * sfreq))
        stop = start + int(round(WINDOW_SECONDS * sfreq))
        assert stop <= raw.n_times, "Selected event extends beyond the recording."
        window = raw.get_data(picks=picks, start=start, stop=stop)
        channel_names = [raw.ch_names[index] for index in picks]
    finally:
        raw.close()
    return np.arange(window.shape[-1]) / sfreq, window, channel_names


examples = []
for command in COMMANDS:
    event = (
        event_table.loc[event_table["command"] == command]
        .sort_values(["session", "run", "onset"])
        .iloc[0]
    )
    examples.append((command, event, load_event_window(event)))

fig, axes = plt.subplots(1, len(examples), figsize=(13, 4.3), sharex=True)
style_figure(
    fig,
    title="Four-second EEG windows aligned to real BIDS events",
    subtitle="First valid occurrence of each observed motor-imagery command",
    source="Amplitude in µV; traces are vertically offset for readability.",
    grid_axis="x",
)
fig.subplots_adjust(top=0.72, bottom=0.28, wspace=0.34)

for ax, (command, event, (time, window, channel_names)) in zip(axes, examples):
    microvolts = window * 1e6
    spacing = max(float(np.nanpercentile(np.abs(microvolts), 95)) * 2.6, 10.0)
    for channel_index, (channel_name, trace) in enumerate(
        zip(channel_names, microvolts)
    ):
        offset = channel_index * spacing
        ax.plot(time, trace + offset, lw=0.75, color=COMMAND_COLORS[command])
        ax.text(-0.1, offset, channel_name, ha="right", va="center", fontsize=7)
    ax.axvline(0, color="#64748B", lw=0.8, linestyle="--")
    ax.set(
        title=command.replace("_", " ").title(),
        xlabel="Seconds after BIDS event",
        yticks=[],
    )
    ax.text(
        0.5,
        -0.17,
        f"session {event.session}, run {event.run}",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=8,
    )
axes[0].set_ylabel("Relative amplitude (µV; offset traces)")
plt.show()

# %% [markdown]
# Step 5. Compare a simple spectrum across sessions
# --------------------------------------------------
#
# A mean Welch PSD is a descriptive diagnostic. It can reveal a recording
# mismatch worth investigating, but it is neither a classifier nor the
# competition metric. We use the first minute and up to eight EEG channels of
# each run so the computation stays small.

# %%
def mean_session_psd(session):
    """Average a short, recorded Welch PSD across the two runs in a session."""
    curves = []
    frequencies = None
    for record in manifest.loc[manifest["session"] == session].itertuples(index=False):
        raw = mne.io.read_raw_edf(
            dataset.data_dir / record.bids_relpath, preload=False, verbose="ERROR"
        )
        try:
            sfreq = float(raw.info["sfreq"])
            picks = mne.pick_types(raw.info, eeg=True, exclude=[])[:8]
            assert len(picks) == 8, "Expected at least eight EEG channels."
            stop = min(raw.n_times, int(round(60 * sfreq)))
            signal = raw.get_data(picks=picks, start=0, stop=stop)
        finally:
            raw.close()
        n_fft = min(1024, signal.shape[-1])
        psd, frequencies = psd_array_welch(
            signal,
            sfreq=sfreq,
            fmin=4.0,
            fmax=40.0,
            n_fft=n_fft,
            n_overlap=n_fft // 2,
            verbose="ERROR",
        )
        curves.append(10 * np.log10(psd.mean(axis=0)))
    return frequencies, np.mean(curves, axis=0)


fig, ax = plt.subplots(figsize=(9.4, 4.1))
style_figure(
    fig,
    title="Session-level spectral diagnostic",
    subtitle="Mean Welch PSD across up to eight channels and the first minute of each run",
    source="Real Zhou2016 recordings; dB re V²/Hz. This is not decoding accuracy.",
    grid_axis="y",
)
for session in SESSIONS:
    frequencies, mean_psd = mean_session_psd(session)
    ax.plot(
        frequencies,
        mean_psd,
        color=SESSION_COLORS[session],
        lw=2.2,
        linestyle="--" if session in HELD_OUT_SESSIONS else "-",
        label=(
            f"session {session} — held out"
            if session in HELD_OUT_SESSIONS
            else f"session {session} — calibration"
        ),
    )
ax.set(xlabel="Frequency (Hz)", ylabel="Power spectral density (dB re V²/Hz)")
ax.legend(frameon=False, loc="upper right")
plt.show()

# %% [markdown]
# Result: hand the audited boundary to NeuralBench
# -------------------------------------------------
#
# EEGDash has produced a real BIDS audit trail: a session-disjoint manifest,
# event-derived candidate windows, and data-quality diagnostics. NeuralBench
# is the complementary tool for frozen targets, training, scoring, and a
# competition submission. Its public Zhou2016 configuration uses the same
# early-to-late session idea:
#
# .. code-block:: bash
#
#    neuralbench eeg motor_imagery --dataset zhou2016
#
# **Modify.** Once the official 2026 data is released, replace the public
# proxy with its MI/calculation/word records while preserving the same rule:
# only labelled early sessions inform the model; later sessions remain held
# out until evaluation.
