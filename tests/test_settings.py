from karaokegrab import settings


def test_defaults_when_missing():
    assert settings.load() == {"last_save_folder": ""}


def test_round_trip():
    settings.save({"last_save_folder": "/Users/me/Music/Karaoke", "unknown": 1})
    assert settings.load() == {"last_save_folder": "/Users/me/Music/Karaoke"}


def test_corrupt_or_wrong_types_fall_back():
    settings.APP_DIR.mkdir(parents=True)
    settings.SETTINGS_PATH.write_text("{not json")
    assert settings.load() == settings.DEFAULTS
    settings.SETTINGS_PATH.write_text('{"last_save_folder": 42}')
    assert settings.load() == settings.DEFAULTS
    settings.SETTINGS_PATH.write_text("[1, 2]")
    assert settings.load() == settings.DEFAULTS


def test_log_appends_with_timestamp():
    settings.log("first")
    settings.log("second")
    lines = settings.LOG_PATH.read_text().splitlines()
    assert [line.split(" ", 1)[1] for line in lines] == ["first", "second"]
    assert lines[0][:4].isdigit()
