EEG/EMG Foundation Challenge 2026
=================================

``tutorial_bci_start_kit.py`` is the first complete EEGDash tutorial for the 2026
challenge. It uses the real Zhou2016 motor-imagery BIDS release (NEMAR
``nm000115``) to make the cross-session BCI workflow inspectable without a
large download: one participant, three sessions, two runs per session, and
about 46.9 MiB of EDF data.

Install the checkout once, then run the script directly:

``python -m pip install -e .``

``python examples/eeg2026/tutorial_bci_start_kit.py``

EEGDash materializes exactly that fixed subset in its configured cache, audits
sessions 0–1 as calibration against session 2 as held out, reads real BIDS
events, and plots the diagnostics directly in the executable gallery lesson.

The Zhou2016 labels are left hand, right hand, and feet. They are a transparent
public proxy for the unreleased 2026 MI/calculation/word task, not a substitute
for the official data or evaluator.

EEGDash owns the BIDS download, event inspection, manifest, and visual
diagnostics. NeuralBench owns target construction, model training, scoring,
and submissions:

``neuralbench eeg motor_imagery --dataset zhou2016``


EMG-to-pose
-----------

``tutorial_emg2pose_start_kit.py`` is the next real-data lesson. It downloads
one 5.8 MiB EMG2Pose BDF from NEMAR ``nm000281`` (16 surface-EMG and 20 joint
channels at 2 kHz), derives a real valid five-second window, plots both signal
types, and opens that exact recording with ``EEGDashDataset.plot()``.

``python examples/eeg2026/tutorial_emg2pose_start_kit.py``

The compact record makes the data interface inspectable; it does not
materialize the release-level metadata needed for the paper's full predefined
split. NeuralBench owns that separate benchmark run on revision ``5fd0c89``:

``neuralbench emg pose -m neuropose``


Sleep onset
-----------

``tutorial_sleep_onset_start_kit.py`` is the benchmark-aligned Sleep-EDF
lesson. It materializes the smallest exact Cassette record from NEMAR
``nm000185``: a 35.5 MiB, seven-channel, 17-hour EDF for
``sub-cassette59/ses-night2``. The lesson finds its real first N2 annotation,
derives the task's 20-minute causal five-second windows and capped targets,
plots the annotations and recorded EEG, then opens that full EDF with
``EEGDashDataset.plot()``.

``python examples/eeg2026/tutorial_sleep_onset_start_kit.py``

The compact lesson is deliberately not a benchmark run. NeuralBench owns its
subject-disjoint 60/20/20 split, model fitting, and binned MAE:

``neuralbench eeg sleep_onset``
