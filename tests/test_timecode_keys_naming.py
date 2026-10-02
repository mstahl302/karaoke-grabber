import pytest

from karaokegrab import keys, naming
from karaokegrab.timecode import format_seconds


# --- timecode ---------------------------------------------------------------

@pytest.mark.parametrize("seconds, text", [
    (0, "0.0 s"),
    (4.5, "4.5 s"),
    (4.44, "4.4 s"),
    (59.9, "59.9 s"),
    (59.96, "1:00.0"),      # rounds up across the minute
    (60, "1:00.0"),
    (334.5, "5:34.5"),
    (3599.95, "1:00:00.0"),
    (3723.04, "1:02:03.0"),
    (-1, "0.0 s"),
])
def test_format_seconds(seconds, text):
    assert format_seconds(seconds) == text


# --- keys -------------------------------------------------------------------

def test_24_unique_keys_in_dropdown_order():
    assert len(keys.KEYS) == 24
    assert len(set(keys.KEYS)) == 24
    assert keys.KEYS[:3] == ("C", "D-flat", "D")
    assert keys.KEYS[11] == "B"
    assert keys.KEYS[12] == "C minor"
    assert keys.KEYS[-1] == "B minor"
    assert all(k.endswith(" minor") for k in keys.MINOR)


def test_lookup_is_forgiving_but_canonical():
    assert keys.lookup("b-flat") == "B-flat"
    assert keys.lookup("  F-SHARP   minor ") == "F-sharp minor"
    assert keys.lookup("Bb") is None
    assert keys.lookup("") is None


# --- naming -----------------------------------------------------------------

def test_filename_convention():
    assert naming.filename("Defying Gravity", "B-flat") == "Defying Gravity - AUDIO - B-flat.mp3"


@pytest.mark.parametrize("title, cleaned", [
    ("AC/DC: Back in Black", "AC-DC- Back in Black"),
    ("  lots   of\tspace \n", "lots of space"),
    ("...hidden", "hidden"),
    ("tab\x00and\x07bell", "tab and bell"),
    ("", "Untitled"),
    ("   ", "Untitled"),
    ("//", "--"),
    ("Café – Ünïcode ✨", "Café – Ünïcode ✨"),
])
def test_clean_title(title, cleaned):
    assert naming.clean_title(title) == cleaned


def test_long_title_is_capped():
    name = naming.filename("x" * 400, "C-sharp minor")
    assert name == "x" * naming.MAX_TITLE_CHARS + " - AUDIO - C-sharp minor.mp3"
    assert len(name.encode()) < 255
