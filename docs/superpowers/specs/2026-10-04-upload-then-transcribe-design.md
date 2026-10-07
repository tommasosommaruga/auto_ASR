# Upload then transcribe

## Goal

Upload audio once from the phone; save it into the library immediately; open that
recording so the user can tap **Transcribe** later (CPU-heavy work is optional
and separate from the upload).

## Flow

1. Client uploads chunks (or a small single POST) until the file is complete.
2. Server assembles the file into `library/<id>/` with `status=pending`, empty
   transcript, title from the filename. Upload session chunks are deleted.
3. Client opens that recording’s detail page.
4. User taps **Transcribe** (same endpoint as “Transcribe again”) when ready.
5. After Whisper finishes, `status=ready` and turns are filled. Audio stays on disk.

## Non-goals

- Background queue / multiple concurrent jobs
- Changing Tailscale or model settings

## API

- `POST /api/uploads/{id}/save` — assemble + library save (no Whisper)
- `POST /api/recordings` — multipart audio save for small files (no Whisper)
- Existing `POST /api/recordings/{id}/transcribe` — run Whisper later
