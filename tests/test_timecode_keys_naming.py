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


def test_filename_without_a_key():
    assert naming.filename("Defying Gravity") == "Defying Gravity - AUDIO.mp3"
    assert naming.filename("Defying Gravity", None) == "Defying Gravity - AUDIO.mp3"
    assert naming.filename("Defying Gravity", "") == "Defying Gravity - AUDIO.mp3"


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


# --- transposing (F17) ------------------------------------------------------

@pytest.mark.parametrize("key, shift, heard", [
    ("B-flat", 2, "C"),             # the spec's example
    ("B-flat", -2, "A-flat"),
    ("C", -1, "B"),
    ("B", 1, "C"),
    ("A minor", -3, "F-sharp minor"),
    ("E minor", 4, "G-sharp minor"),
    ("D", 9, "B"),
    ("D", -9, "F"),
    ("G", 0, "G"),
])
def test_effective_key(key, shift, heard):
    assert keys.effective_key(key, shift) == heard


@pytest.mark.parametrize("scale", [keys.MAJOR, keys.MINOR])
def test_effective_key_every_key_every_shift(scale):
    for i, key in enumerate(scale):
        for shift in range(-keys.MAX_SHIFT, keys.MAX_SHIFT + 1):
            heard = keys.effective_key(key, shift)
            assert heard in scale                       # minor stays minor
            assert scale.index(heard) == (i + shift) % 12
            assert keys.effective_key(heard, -shift) == key


def test_effective_key_rejects_unknown():
    with pytest.raises(ValueError):
        keys.effective_key("H", 1)


def test_shift_label():
    assert keys.shift_label(2) == "+2"
    assert keys.shift_label(-3) == "−3"
    assert keys.shift_label(0) == "0"


def test_filename_uses_the_key_you_hear():
    assert naming.filename("Defying Gravity", "B-flat", 2) == "Defying Gravity - AUDIO - C.mp3"
    assert naming.filename("Defying Gravity", "A minor", -3) == "Defying Gravity - AUDIO - F-sharp minor.mp3"


def test_filename_with_a_shift_but_no_key():
    assert naming.filename("Defying Gravity", None, 2) == "Defying Gravity - AUDIO (+2).mp3"
    assert naming.filename("Defying Gravity", None, -2) == "Defying Gravity - AUDIO (-2).mp3"
    assert naming.filename("Defying Gravity", None, 0) == "Defying Gravity - AUDIO.mp3"


def test_short_names_for_the_dropdown():
    assert keys.short_name("B-flat") == "B♭"
    assert keys.short_name("F-sharp") == "F♯"
    assert keys.short_name("C minor") == "Cm"
    assert keys.short_name("C-sharp minor") == "C♯m"
    assert len(set(keys.SHORT)) == 24
    assert all(keys.from_short(keys.short_name(k)) == k for k in keys.KEYS)
    assert keys.from_short("B-flat") is None


def test_filename_with_a_speed():
    assert naming.filename("Defying Gravity", "B-flat", 2, 75) == "Defying Gravity - AUDIO - C (75%).mp3"
    assert naming.filename("Defying Gravity", None, 2, 75) == "Defying Gravity - AUDIO (+2, 75%).mp3"
    assert naming.filename("Defying Gravity", None, -1, 120) == "Defying Gravity - AUDIO (-1, 120%).mp3"
    assert naming.filename("Defying Gravity", None, 0, 75) == "Defying Gravity - AUDIO (75%).mp3"
    assert naming.filename("Defying Gravity", "D", 0, 100) == "Defying Gravity - AUDIO - D.mp3"
