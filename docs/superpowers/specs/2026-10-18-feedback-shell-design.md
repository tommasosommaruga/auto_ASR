# Feedback shell for dock, library, and detail

## Problem

The app already records, saves pending audio, polls `/api/activity`, and draws a
live mixer signal plane — but user feedback is scattered: status lines compete,
pending vs ready is easy to miss, and dock / library / detail do not read as one
professional, dynamic story. For triage-style use (and as a reference UX for a
later offline speech-to-speech app), the user needs a clear vertical slice:

**Record → Saved (pending) → Working (phase) → Ready**, with honest offline and
soft-failure behavior, without a static mock page.

## Goals

- One client **stage model** is the single writer for visible stage text.
- Broader visual refresh of **dock, library, and detail** around that feedback.
- Thin end-to-end slice: live meter while recording, Pending badge after save,
  Working phases from activity, Ready when transcript exists.
- Keep existing backend contracts; audio remains source of truth; original never
  overwritten.

## Non-goals

- Settings UI redesign.
- Android native or WebView shell changes.
- TTS reply / full speech-to-speech pipeline.
- New server activity phases beyond current download / transcribe / translate
  (plus client-side upload / recording stages).
- Diarization UX polish.
- Silent downloads or concurrent heavy jobs.

## Approach

**Feedback shell rewrite:** rebuild chrome for dock / library / detail around a
small stage model. Inputs stay:

- Mic / mixer levels → signal plane (`static/audio-mixer.js`)
- Save / upload → library `pending` / `status`
- `/api/activity` poll (~400ms) → `phase`, `label`, `received`, `total`

The stage model maps those into UI stages and paints one coherent chrome.

## Stages

| Stage | Meaning | Primary sources |
|-------|---------|-----------------|
| Idle | Ready to capture (dock quiet state) | no recording, no active job |
| Recording | Mic live | record button / mixer |
| Saving | Upload / write in flight | client upload progress |
| Pending | Audio saved, no usable transcript yet | `pending` / empty turns |
| Working | Server job active | `/api/activity` phases |
| Ready | Transcript present (item-level) | non-pending item with turns |
| Failed | Soft fail; audio kept if saved | upload/network/job error |

Dock strip steps are capture-flow only: **Idle · Recording · Saving · Working**.
**Pending / Ready / Failed** are item-level (library badge + detail status), not
extra strip steps. Working sub-labels reuse activity phases: download,
transcribe, translate (client upload maps to Saving).

## Surfaces

### Dock

- Stage strip: Idle · Recording · Saving · Working (current step emphasized).
- Signal plane primary while recording or mixer open (raw / removed / processed).
- Job progress lives with the strip (label + bar + Cancel when upload).
- Languages and people remain; Record / Stop stay primary actions.

### Library

- Row badge: `Pending` or `Ready`.
- Active job mirrored via shared stage label (banner or row hint) so status is
  not orphaned at the page bottom.
- Short empty state: record or upload.

### Detail

- Status line: Pending / Working · … / Ready / Failed (same vocabulary).
- Context-aware CTA unchanged in behavior (`Transcribe` / `Translate` / `Apply`).
- Progress under status; empty transcript copy stays honest for pending.
- Mixer and listen/source controls kept; hierarchy is status → audio → transcript.

## Data flow

```
Record → stage Recording → signal plane frames
Stop → stage Saving → upload progress
Success → pending item → stage Pending (+ library badge)
Transcribe / translate / apply
  → pack consent if needed
  → poll /api/activity → stage Working(phase, label, bytes)
  → paint detail and/or dock from the same stage model
Clear → Ready if transcript; else Pending or Failed soft
Mixer knobs → redraw plane only; never overwrite original
```

Existing `pollActivity` / `paintActivity` / client upload progress become
**inputs** to the stage model, not competing status writers.

## Errors and offline

- Missing packs offline: keep installed-only honesty; stay Pending with clear
  copy; Install only when online after consent.
- Upload / network fail: Failed soft; keep audio if already saved; Cancel for
  in-flight chunked upload.
- Empty / failed speech: keep folder; return to Pending with soft-fail copy.
- One heavy job: block other heavy actions as today; strip shows global phase.
- Stalled activity: keep last label + indeterminate bar; do not flash Idle.

## Visual direction

- Refresh dock, library, and detail hierarchy, type, and spacing around the
  stage strip and badges.
- Stay in the existing light paper / accent family unless small token tweaks are
  required for strip and meter readability.
- Dynamic feedback (live meter, live phases), not a static prototype page.

## Files expected to change

- `static/index.html` — dock stage strip, library/detail status structure
- `static/app.css` — feedback shell visual refresh
- `static/app.js` — stage model; wire record/save/activity/library/detail
- `static/audio-mixer.js` — only if plane integration needs small hooks

Backend (`activity.py`, `server.py`, `library.py`) unchanged unless a missing
label blocks the slice (prefer client mapping first).

## Done when

User can: open app → record with live meter → stop → see **Pending** → tap
Transcribe → see **Working · …** → get **Ready**, with soft failures keeping
audio and offline packs not pretending to work.

## Testing

- Manual: record → pending badge → transcribe phases → ready transcript.
- Manual: cancel or fail upload; audio kept when already saved.
- Manual: offline / missing pack path still blocks install without silent pull.
- Existing unit tests for library pending and activity remain green; add a small
  frontend-facing test only if a pure stage-mapping helper is extracted and
  easy to unit-test in Python or a tiny shared fixture — do not block the slice
  on a new browser test harness.
