import karaokegrab
import main


def test_window_opens_and_closes_cleanly():
    app = main.App()
    app.update_idletasks()
    assert app.title() == "Karaoke Grabber"
    assert karaokegrab.__version__
    app._on_close()
    app._on_close()  # idempotent, as ⌘Q and the close box can both fire
