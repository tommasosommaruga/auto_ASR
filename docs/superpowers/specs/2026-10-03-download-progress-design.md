# Download progress and install consent

## Problem

1. While installing a speech model (e.g. `medium.en`), the UI can show a fixed
   line like `Speech model medium.en · 1457 MB left` and stop updating. Hugging
   Face often reports the total size early, then goes quiet on byte updates
   (especially with Xet), so `activity.received` stays near zero.
2. Choosing **Not now** on the install dialog can still result in a speech-model
   download, because transcription loads the model through `_get_whisper`, which
   calls `_ensure_cached_speech_model` and downloads without going through
   `/api/install`.

## Goals

- Keep the existing progress bar and calm one-line status.
- Make download status move reliably while a speech model is installing.
- Download speech models only after the user confirms Install.
- Avoid speed, ETA, or other noisy chrome.

## Non-goals

- Redesigning the dialog or dock layout.
- Cancelling an in-flight download from the UI (out of scope).
- Changing how translation or speaker files are fetched later in the job.

## Approach

Watch the model’s Hugging Face cache on disk during speech-model install, and
feed that into the existing `activity` snapshot. Keep HF tqdm hooks as a
secondary signal. Harden consent so transcription never starts a Hub download.

## Data flow

```
/api/install
  → activity.begin("download", label)
  → start disk ticker (~0.5s) for this model’s cache tree
  → snapshot_download(... tqdm_class=_HubProgress)
       ├─ tqdm updates → activity.note(received, total)
       └─ ticker → activity.note(max(tqdm, disk_bytes), total_or_known)
  → stop ticker
  → activity.clear()
```

Frontend keeps polling `/api/activity` every 400ms and painting the same bar.

### Disk measurement

- Scope: the whisper cache directory for the model being installed
  (`WHISPER_DIR` / Hugging Face snapshot + blobs for that repo).
- Count bytes of relevant files, including incomplete/partial download files.
- `received = max(last_tqdm_received, disk_bytes)`.
- Prefer HF `total` when known; never invent a total from disk alone if HF has
  not reported one (indeterminate bar stays valid).
- Ticker runs only for speech-model install via `snapshot_download`; URL-based
  downloads (speakers) and translation installs keep current byte streaming.

### Activity contract

No new API fields required. Continue exposing:

- `active`, `phase`, `label`, `received`, `total`, `remaining`

Optional later: none for this change.

## UI

Same progress track/bar.

When `total > 0`:

`{label} · {percent}% · {received} / {total}`

Example: `Speech model medium.en · 12% · 180 / 1457 MB`

When `total == 0`: keep the indeterminate sliding bar and `{label}` only.

No speed, ETA, or extra badges.

## Install consent

1. Speech preset downloads happen only inside `/api/install` after the user
   confirms Install in the UI.
2. `_get_whisper` must not call Hub download helpers. If the model is not already
   on disk (`speech_ready` is false), fail with a clear error asking the user to
   install it first.
3. `WhisperModel(...)` must not be allowed to silently download either: only
   construct it when `speech_ready` is true (local/cache path already present).
4. UI gate stays: **Not now** → `blocked`, no `/api/install` call.

Translation and speaker downloads that occur mid-transcription are unchanged by
this consent rule (already documented as “later, while the transcript is being
made”).

## Error handling

- Disk ticker failures are ignored for that tick; download continues.
- If install fails, stop ticker and clear activity (existing `finally` behavior).
- If transcription is requested without an installed model, return a user-facing
  error; do not start a download.

## Testing

- Activity/disk helper: received advances when incomplete cache files grow;
  `received` never goes backwards relative to the max of tqdm and disk.
- Consent: loading a missing preset via the transcription path does not create
  or grow Hub cache files; it errors instead.
- Existing remaining-bytes activity test still passes (or is updated for the
  richer label only on the frontend).

## Files likely touched

- `activity.py` — optional helpers if note/max semantics need centralizing
- `pipeline.py` — disk ticker around speech `snapshot_download`; remove
  auto-download from `_get_whisper`
- `static/app.js` — progress label format (`%` + received/total)
- `tests/test_activity.py` and/or new download-consent/progress tests
