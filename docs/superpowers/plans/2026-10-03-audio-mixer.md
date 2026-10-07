# Audio Mixer Implementation Plan

> **For agentic workers:** Implement task-by-task. Prefer TDD for library/API.

**Goal:** Browser mixer (easy + advanced), optional cleaned audio, choose source for STT.

**Files**
- `library.py` — cleaned audio + transcript_audio fields
- `server.py` — cleaned upload/delete, audio source query, retranscribe
- `static/audio-mixer.js` — Web Audio graph + offline process
- `static/app.js`, `index.html`, `app.css` — UI wiring
- `tests/test_library.py` — cleaned audio persistence

## Tasks

1. Library: store/load/delete cleaned audio + transcript_audio; expose URLs in detail.
2. Server: endpoints for cleaned audio and retranscribe with `audio_source`.
3. `audio-mixer.js`: presets, easy/advanced settings, live graph, offline WAV export.
4. Dock + detail UI: mixer panel, source select, save cleaned, always-visible Transcribe again.
5. Wire live MediaRecorder through the mixer graph.
6. Manual smoke: record with gain, clean quiet file, save cleaned, transcribe cleaned.
