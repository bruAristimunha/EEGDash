"""Guard the real-data 2026 gallery tutorial contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = ROOT / "examples/eeg2026/tutorial_bci_start_kit.py"
EMG_TUTORIAL = ROOT / "examples/eeg2026/tutorial_emg2pose_start_kit.py"
SLEEP_TUTORIAL = ROOT / "examples/eeg2026/tutorial_sleep_onset_start_kit.py"


def test_bci_start_kit_is_a_real_data_pydata_gallery_tutorial():
    """Keep the BCI lesson executable, real-data-only, and cell-oriented."""
    assert TUTORIAL.is_file()
    source = TUTORIAL.read_text(encoding="utf-8")

    assert 'DATASET = "nm000115"' in source
    assert 'neuralbench eeg motor_imagery --dataset zhou2016' in source
    assert "EEGDASH_RUN_2026_TUTORIALS" not in source
    assert "os.environ" not in source
    assert "def main()" not in source
    assert ".. figure::" not in source
    assert "FancyBboxPatch" not in source
    assert source.count("plt.show()") >= 3
    assert "get_default_cache_dir" in source
    assert "assert len(calibration) == 4" in source
    assert "assert len(held_out) == 2" in source
    assert "# Step 1." in source
    assert "# Step 2." in source
    assert "# Step 3." in source


def test_emg2pose_start_kit_is_a_real_data_pydata_gallery_tutorial():
    """Keep the EMG lesson small, real-data-only, and viewer-native."""
    assert EMG_TUTORIAL.is_file()
    source = EMG_TUTORIAL.read_text(encoding="utf-8")

    assert 'DATASET = "nm000281"' in source
    assert 'SUBJECT = "04"' in source
    assert 'SESSION = "02"' in source
    assert 'RUN = "30"' in source
    assert "recording-left_emg.bdf" in source
    assert "BAD_IK" in source
    assert "WINDOW_SECONDS = 5.0" in source
    assert "dataset.plot(index=0" in source
    assert "neuralbench emg pose -m neuropose" in source
    assert "EEGDASH_RUN_2026_TUTORIALS" not in source
    assert "os.environ" not in source
    assert "np.random" not in source
    assert "def main()" not in source
    assert source.count("plt.show()") >= 2


def test_sleep_onset_start_kit_is_a_real_data_pydata_gallery_tutorial():
    """Keep the sleep-onset lesson real-data-only and benchmark-aligned."""
    assert SLEEP_TUTORIAL.is_file()
    source = SLEEP_TUTORIAL.read_text(encoding="utf-8")

    assert 'DATASET = "nm000185"' in source
    assert 'SUBJECT = "cassette59"' in source
    assert 'SESSION = "night2"' in source
    assert "Sleep stage 2" in source
    assert "WINDOW_SECONDS = 5.0" in source
    assert "MAX_PRE_N2_SECONDS = 1200.0" in source
    assert "dataset.plot(index=0" in source
    assert "neuralbench eeg sleep_onset" in source
    assert "EEGDASH_RUN_2026_TUTORIALS" not in source
    assert "os.environ" not in source
    assert "np.random" not in source
    assert "def main()" not in source
    assert source.count("plt.show()") >= 2
