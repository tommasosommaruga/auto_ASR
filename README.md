# auto_ASR

Local speech-to-text for recordings and phone uploads. The Mac runs Whisper;
browsers and the Android WebView only record, upload, and review transcripts.

## Features

- HTTPS local server with a library of recordings
- Chunked, resumable uploads from phone or desktop
- Upload first, transcribe later
- Offline use when speech models are already installed (downloads need internet)
- Apple Silicon MLX GPU when weights are present; otherwise CUDA or CPU
- Optional translation and speaker labels

## Requirements

- Python 3.9+
- macOS Apple Silicon recommended for MLX; Linux/Windows with CUDA also work
- Optional: Android Studio for the WebView app in `android/`

## Quick start

```bash
./scripts/run.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py --https --host 0.0.0.0
```

Open the printed HTTPS URL. Trust the local certificate when prompted.
Configure speech model and languages in Settings. Missing models download only
while online; offline, only installed options stay available.

## Android

See [android/README.md](android/README.md). The phone talks to this server; it
does not run Whisper on-device.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## Privacy

`.env`, TLS certs, `settings.json`, model caches, and the `library/` folder are
gitignored and stay on your machine.
