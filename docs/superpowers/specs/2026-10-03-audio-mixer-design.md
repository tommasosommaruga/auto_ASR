# Audio mixer, cleaned copy, and transcription source

## Goals

- Easy mic/mixer controls in the web app (live record + saved files).
- Advanced filters collapsed by default.
- Cleaned audio is optional to save; original is never overwritten.
- User picks Original vs Cleaned for transcription.
- Presets and last settings remembered in the browser.

## Non-goals

- Server-side DSP / ffmpeg.
- Studio-grade denoise / AI enhancement.
- Multi-track editing.

## Approach

Browser Web Audio for live chain and offline clean of a saved file.
Library stores optional `audio_cleaned` and `transcript_audio` (`original`|`cleaned`).

## Data

- `audio` — original capture (required).
- `audio_cleaned` — optional saved clean file.
- Preview clean stays in memory until **Save cleaned**.
- Transcription uses the selected source (preview once, or saved cleaned).

## UI

- Easy: meter, gain, auto-gain, preset, listen, apply preview, save cleaned, source select.
- Advanced (hidden): high-pass, low-pass, gate, compression, hum notch, AGC target/speed.

## API

- `GET .../audio?source=original|cleaned`
- `PUT .../cleaned` upload cleaned blob
- `DELETE .../cleaned`
- `POST .../transcribe` re-run STT with language, translate_to, audio_source
