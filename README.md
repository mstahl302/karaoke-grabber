# Karaoke Grabber

![tests](https://github.com/mstahl302/karaoke-grabber/actions/workflows/ci.yml/badge.svg)

A small macOS app that turns a YouTube karaoke (backing) track into a
trimmed, correctly named MP3: `<Song Title> - AUDIO - <key>.mp3`.

**Status:** in development (milestone M0, environment). The full README
arrives with V1; its outline is in
[docs/dev_environment.md](docs/dev_environment.md) §6.

## Requirements

- macOS on Apple Silicon
- [Homebrew](https://brew.sh), then `brew install yt-dlp ffmpeg deno`
- Python 3.14 from [python.org](https://www.python.org/downloads/macos/)
  (it ships Tk 9; the system `/usr/bin/python3` doesn't)

## Develop & test

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python main.py
.venv/bin/python -m pytest
```

## Docs

- [Product spec](docs/product_spec.md)
- [Architecture](docs/architecture.md)
- [Build plan](docs/build_plan.md)
- [Dev environment](docs/dev_environment.md)
- [Roadmap](docs/roadmap.md)

## License

MIT; see [LICENSE](LICENSE).
