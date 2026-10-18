# Feedback Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dock, library, and detail share one dynamic feedback story — Record → Pending → Working → Ready — with a live signal plane and a visual refresh of those three surfaces.

**Architecture:** Add a pure `stage-model.js` that resolves UI stage from recording/upload/activity/item flags. `app.js` feeds that model and is the only writer of stage chrome (strip, badges, detail status). Keep `/api/activity`, pending library flags, and `audio-mixer.js` signal plane as inputs. Refresh CSS/HTML for dock/library/detail only.

**Tech Stack:** Vanilla JS (ES modules or IIFE on `window`), existing FastAPI `/api/activity`, CSS custom properties, Node `--test` for the pure stage helper.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-18-feedback-shell-design.md`
- Dock strip steps only: Idle · Recording · Saving · Working
- Item-level only: Pending · Ready · Failed
- No Settings redesign; no Android changes; no new server phases
- No silent downloads; one heavy job; original audio never overwritten
- Prefer client mapping over backend changes
- Skip git commits unless the user asks
- Confirm before overwriting large existing blocks in `static/app.js` / `static/audio-mixer.js` that already have uncommitted local edits

## File map

| File | Responsibility |
|------|----------------|
| `static/stage-model.js` | Pure resolve/paint helpers for stage + labels |
| `tests/test_stage_model.mjs` | Node unit tests for resolve rules |
| `static/index.html` | Stage strip markup; status hooks; script include; cache-bust `?v=` |
| `static/app.js` | Wire record/save/activity/library/detail to stage model |
| `static/app.css` | Visual refresh for dock strip, badges, detail status, hierarchy |
| `static/audio-mixer.js` | Touch only if plane must stay visible while recording (prefer CSS/HTML first) |

---

### Task 1: Pure stage model + unit tests

**Files:**
- Create: `static/stage-model.js`
- Create: `tests/test_stage_model.mjs`

**Interfaces:**
- Produces:
  - `StageModel.resolve(input) -> { flow, item, label, progress }`
  - `input` shape:
    ```js
    {
      recording: boolean,          // mic live
      saving: boolean,             // client upload in flight
      failed: boolean,             // soft fail after save attempt or job
      failMessage: string,         // optional
      activityActive: boolean,
      activityPhase: string,       // "", "download", "transcribe", "translate"
      activityLabel: string,
      received: number,
      total: number,
      itemPending: boolean | null, // null = no item in focus
      hasTranscript: boolean,
    }
    ```
  - `flow`: `"idle" | "recording" | "saving" | "working"`
  - `item`: `"none" | "pending" | "ready" | "failed"`
  - `label`: short user-facing string
  - `progress`: `{ mode: "hidden" | "determinate" | "indeterminate", ratio: number, text: string }`
- Consumes: nothing

- [ ] **Step 1: Write failing Node tests**

Create `tests/test_stage_model.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

// Load as classic script into a sandbox, or convert stage-model to export for Node.
// Prefer: stage-model.js assigns globalThis.StageModel and also exports when import.meta ok.
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
await import(pathToFileURL(path.join(root, "static/stage-model.js")).href);
const { resolve } = globalThis.StageModel;

const base = () => ({
  recording: false,
  saving: false,
  failed: false,
  failMessage: "",
  activityActive: false,
  activityPhase: "",
  activityLabel: "",
  received: 0,
  total: 0,
  itemPending: null,
  hasTranscript: false,
});

test("idle when nothing happening", () => {
  const out = resolve(base());
  assert.equal(out.flow, "idle");
  assert.equal(out.item, "none");
});

test("recording beats idle", () => {
  const out = resolve({ ...base(), recording: true });
  assert.equal(out.flow, "recording");
  assert.match(out.label, /recording/i);
});

test("saving maps to flow saving", () => {
  const out = resolve({ ...base(), saving: true });
  assert.equal(out.flow, "saving");
});

test("activity download is working with determinate progress", () => {
  const out = resolve({
    ...base(),
    activityActive: true,
    activityPhase: "download",
    activityLabel: "Speech model small",
    received: 50,
    total: 100,
  });
  assert.equal(out.flow, "working");
  assert.equal(out.progress.mode, "determinate");
  assert.equal(out.progress.ratio, 0.5);
});

test("activity transcribe is working indeterminate", () => {
  const out = resolve({
    ...base(),
    activityActive: true,
    activityPhase: "transcribe",
  });
  assert.equal(out.flow, "working");
  assert.equal(out.progress.mode, "indeterminate");
  assert.match(out.label, /transcrib/i);
});

test("item pending and ready", () => {
  assert.equal(resolve({ ...base(), itemPending: true }).item, "pending");
  assert.equal(
    resolve({ ...base(), itemPending: false, hasTranscript: true }).item,
    "ready",
  );
});

test("failed soft keeps item failed", () => {
  const out = resolve({
    ...base(),
    failed: true,
    failMessage: "Upload failed",
    itemPending: true,
  });
  assert.equal(out.item, "failed");
  assert.match(out.label, /upload failed/i);
});

test("recording priority over activity", () => {
  const out = resolve({
    ...base(),
    recording: true,
    activityActive: true,
    activityPhase: "transcribe",
  });
  assert.equal(out.flow, "recording");
});
```

- [ ] **Step 2: Run tests — expect FAIL** (module missing)

```bash
node --test tests/test_stage_model.mjs
```

Expected: fail to resolve `StageModel` / file missing.

- [ ] **Step 3: Implement `static/stage-model.js`**

```js
/* Pure stage resolution for dock strip + item badges. No DOM. */
(function (root) {
  function resolve(input) {
    const i = input || {};
    const recording = Boolean(i.recording);
    const saving = Boolean(i.saving);
    const failed = Boolean(i.failed);
    const activityActive = Boolean(i.activityActive);
    const phase = String(i.activityPhase || "");
    const activityLabel = String(i.activityLabel || "");
    const received = Math.max(0, Number(i.received) || 0);
    const total = Math.max(0, Number(i.total) || 0);
    const failMessage = String(i.failMessage || "");

    let flow = "idle";
    let label = "";
    let progress = { mode: "hidden", ratio: 0, text: "" };

    if (recording) {
      flow = "recording";
      label = "Recording";
    } else if (saving) {
      flow = "saving";
      label = "Saving audio…";
      progress = { mode: "indeterminate", ratio: 0, text: label };
    } else if (activityActive) {
      flow = "working";
      if (phase === "download") {
        if (total > 0) {
          const ratio = Math.max(0, Math.min(1, received / total));
          const percent = Math.round(ratio * 100);
          label = `${activityLabel || "Downloading"} · ${percent}%`;
          progress = {
            mode: "determinate",
            ratio,
            text: label,
          };
        } else {
          label = activityLabel || "Downloading…";
          progress = { mode: "indeterminate", ratio: 0, text: label };
        }
      } else if (phase === "translate") {
        label = "Working · Translating…";
        progress = { mode: "indeterminate", ratio: 0, text: label };
      } else {
        label = "Working · Transcribing…";
        progress = { mode: "indeterminate", ratio: 0, text: label };
      }
    }

    let item = "none";
    if (failed) {
      item = "failed";
      label = failMessage || "Something went wrong — audio kept if already saved";
    } else if (i.itemPending === true) {
      item = "pending";
      if (flow === "idle") label = "Pending — audio saved";
    } else if (i.itemPending === false && i.hasTranscript) {
      item = "ready";
      if (flow === "idle") label = "Ready";
    } else if (i.itemPending === false && !i.hasTranscript) {
      item = "pending";
      if (flow === "idle") label = "Pending — no speech found, audio kept";
    }

    return { flow, item, label, progress };
  }

  const api = { resolve };
  root.StageModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
```

Priority order (must match tests): **recording > saving > activity > idle**; item flags independent except failed overrides item badge.

- [ ] **Step 4: Run tests — expect PASS**

```bash
node --test tests/test_stage_model.mjs
```

Expected: all tests pass.

- [ ] **Step 5: Commit only if user asked**

---

### Task 2: HTML shell — stage strip + status hooks

**Files:**
- Modify: `static/index.html`
- Modify: `static/app.js` (querySelectors only if needed after markup)

**Interfaces:**
- Consumes: none yet
- Produces DOM ids:
  - `#stage-strip` with children `[data-flow="idle|recording|saving|working"]`
  - `#stage-label` (live region text under strip)
  - `#library-job-banner` (optional slim banner above list)
  - `#detail-stage` (detail status line; can replace or wrap `#detail-status`)
  - Script: `/static/stage-model.js?v=N` before `app.js`; bump `app.js` / `app.css` `?v=`

- [ ] **Step 1: Add dock stage strip markup**

Inside `#dock`, **above** `#timer` / job status, insert:

```html
<div id="stage-strip" class="stage-strip" aria-label="Capture stage">
  <span data-flow="idle" class="stage-step is-current">Idle</span>
  <span data-flow="recording" class="stage-step">Recording</span>
  <span data-flow="saving" class="stage-step">Saving</span>
  <span data-flow="working" class="stage-step">Working</span>
</div>
<p id="stage-label" class="stage-label" role="status" aria-live="polite"></p>
```

Keep `#job-status`, `#job-progress`, and Cancel; they become driven by the stage model in Task 3 (do not delete yet).

- [ ] **Step 2: Library banner + detail stage**

In `#library-view`, above `#library-list`:

```html
<p id="library-job-banner" class="library-job-banner" hidden role="status"></p>
```

In `#detail-view`, near meta / before progress, ensure a dedicated line:

```html
<p id="detail-stage" class="detail-stage" role="status" aria-live="polite"></p>
```

(`#detail-status` may remain as a fallback sink during migration; Task 3 should prefer `#detail-stage`.)

- [ ] **Step 3: Include stage-model script**

Before `app.js`:

```html
<script src="/static/stage-model.js?v=27"></script>
<script src="/static/audio-mixer.js?v=27"></script>
<script src="/static/app.js?v=27"></script>
```

Bump CSS `?v=` on the stylesheet link to match.

- [ ] **Step 4: Manual check**

Open the page: strip visible in dock; no JS errors in console (`StageModel` defined).

- [ ] **Step 5: Commit only if user asked**

---

### Task 3: Wire stage model in `app.js`

**Files:**
- Modify: `static/app.js`

**Interfaces:**
- Consumes: `globalThis.StageModel.resolve`
- Produces:
  - `feedbackState` object matching Task 1 `input`
  - `setFeedback(partial)` merges state and calls `paintFeedback()`
  - `paintFeedback()` updates strip `.is-current`, `#stage-label`, job/detail progress, `#library-job-banner`, `#detail-stage`, and stops writing competing strings into `#job-status` / `#detail-status` for the same facts

- [ ] **Step 1: Add state + paint helpers near top of app logic**

```js
const stageStrip = document.querySelector("#stage-strip");
const stageLabel = document.querySelector("#stage-label");
const libraryJobBanner = document.querySelector("#library-job-banner");
const detailStage = document.querySelector("#detail-stage");

const feedbackState = {
  recording: false,
  saving: false,
  failed: false,
  failMessage: "",
  activityActive: false,
  activityPhase: "",
  activityLabel: "",
  received: 0,
  total: 0,
  itemPending: null,
  hasTranscript: false,
};

function setFeedback(partial) {
  Object.assign(feedbackState, partial || {});
  paintFeedback();
}

function paintFeedback() {
  const out = StageModel.resolve(feedbackState);
  if (stageStrip) {
    for (const step of stageStrip.querySelectorAll("[data-flow]")) {
      step.classList.toggle("is-current", step.getAttribute("data-flow") === out.flow);
    }
  }
  if (stageLabel) stageLabel.textContent = out.flow === "idle" ? "" : out.label;

  const onDetail = document.body.classList.contains("is-detail");
  const box = onDetail ? detailProgress : jobProgress;
  const track = onDetail ? detailTrack : jobTrack;
  const bar = onDetail ? detailBar : jobBar;
  const labelEl = onDetail ? detailProgressLabel : jobProgressLabel;

  if (out.progress.mode === "hidden") {
    hideProgress(box, bar, track);
    document.body.classList.remove("is-downloading");
  } else {
    box.hidden = false;
    document.body.classList.add("is-downloading");
    labelEl.textContent = out.progress.text;
    if (out.progress.mode === "determinate") {
      const percent = Math.round(out.progress.ratio * 100);
      bar.style.width = `${percent}%`;
      bar.classList.remove("is-unknown");
      track.setAttribute("aria-valuenow", String(percent));
    } else {
      bar.style.width = "";
      bar.classList.add("is-unknown");
      track.setAttribute("aria-valuenow", "0");
    }
  }

  if (libraryJobBanner) {
    const show = !onDetail && out.flow === "working";
    libraryJobBanner.hidden = !show;
    libraryJobBanner.textContent = show ? out.label : "";
  }
  if (detailStage) {
    if (out.item === "failed") detailStage.textContent = out.label;
    else if (out.flow === "working") detailStage.textContent = out.label;
    else if (out.item === "pending") {
      detailStage.textContent = "Pending — audio saved. Tap Transcribe when ready.";
    } else if (out.item === "ready") detailStage.textContent = "Ready";
    else detailStage.textContent = "";
  }

  // Clear legacy duplicate status when stage chrome owns the message.
  if (out.flow !== "idle" || out.item === "failed") {
    if (!onDetail) jobStatus.textContent = "";
    else detailStatus.textContent = "";
  }
}
```

- [ ] **Step 2: Hook recording lifecycle**

In `startRecording` after mic starts successfully:

```js
setFeedback({ recording: true, failed: false, failMessage: "" });
```

In recorder `stop` handler **before** upload:

```js
setFeedback({ recording: false, saving: true, failed: false });
```

On mic start failure path:

```js
setFeedback({ recording: false });
```

- [ ] **Step 3: Hook upload / save**

Wherever `showClientProgress` starts an upload (`Uploading` / `Resuming`):

```js
setFeedback({ saving: true, failed: false });
```

On successful library accept (pending item created) — where `recordingPending = true` / open detail after upload:

```js
setFeedback({
  saving: false,
  itemPending: true,
  hasTranscript: false,
  failed: false,
});
```

On upload failure (catch paths that today set `jobStatus`):

```js
setFeedback({
  saving: false,
  failed: true,
  failMessage: messageFrom(payload, "Upload failed — try again"),
});
```

Also update `showClientProgress` to call `setFeedback` with determinate saving progress if desired by extending `StageModel.resolve` later; for the slice, indeterminate Saving + existing progress bar text via `setFeedback({ saving: true })` plus keep `showClientProgress` writing `jobProgressLabel` is OK **only until** paintFeedback owns progress — then route upload ratios through feedbackState (`received`/`total` + `saving: true`) and teach `resolve` to treat saving like determinate when `total > 0`.

Minimal addition to `resolve` for determinate save:

```js
} else if (saving) {
  flow = "saving";
  if (total > 0) {
    const ratio = Math.max(0, Math.min(1, received / total));
    const percent = Math.round(ratio * 100);
    label = `Saving · ${percent}%`;
    progress = { mode: "determinate", ratio, text: label };
  } else {
    label = "Saving audio…";
    progress = { mode: "indeterminate", ratio: 0, text: label };
  }
}
```

Update Node tests accordingly if you add this in the same task.

- [ ] **Step 4: Hook activity polling**

Change `paintActivity` to feed the model instead of writing status directly:

```js
function paintActivity(payload, statusEl, box, track, bar, labelEl) {
  const labelText = String((labelEl && labelEl.textContent) || "");
  const clientUpload = /^(Uploading|Resuming|Reconnecting|Connection blip|Saving)/.test(labelText);
  if (clientUpload && feedbackState.saving) {
    if (!payload.active) return;
  }
  setFeedback({
    activityActive: Boolean(payload.active),
    activityPhase: payload.active ? String(payload.phase || "") : "",
    activityLabel: String(payload.label || ""),
    received: Number(payload.received) || 0,
    total: Number(payload.total) || 0,
  });
}
```

Remove duplicate bar painting from `paintActivity` once `paintFeedback` owns it. Keep `startWatch` / `stopWatch`; on `stopWatch` call:

```js
setFeedback({
  activityActive: false,
  activityPhase: "",
  activityLabel: "",
  received: 0,
  total: 0,
});
```

- [ ] **Step 5: Hook detail / library item flags**

In `applyRecordingPayload` after `recordingPending` is set:

```js
const turns = payload.turns || payload.segments || [];
setFeedback({
  itemPending: recordingPending || !(turns && turns.length),
  hasTranscript: Boolean(turns && turns.length),
  failed: false,
});
```

(Use the same transcript empty check the UI already uses for `#turns` / empty transcript.)

When returning to library (`showLibrary`), clear item focus:

```js
setFeedback({ itemPending: null, hasTranscript: false });
```

- [ ] **Step 6: Manual vertical slice**

1. Record → strip **Recording**, plane moves  
2. Stop → **Saving** → library/detail **Pending**  
3. Transcribe → **Working** + banner/detail label  
4. Finish → **Ready**  
5. Force upload fail → **Failed** soft, audio kept if saved  

- [ ] **Step 7: Commit only if user asked**

---

### Task 4: Library badges + empty copy

**Files:**
- Modify: `static/app.js` (`renderRecording`, empty note)
- Modify: `static/app.css` (badge styles — may land with Task 5)

**Interfaces:**
- Consumes: `item.pending` / `item.status`
- Produces: each row includes `<span class="recording-badge is-pending|is-ready">`

- [ ] **Step 1: Update `renderRecording`**

```js
function renderRecording(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "recording";
  const pending = Boolean(item.pending || item.status === "pending");

  const head = document.createElement("div");
  head.className = "recording-head";
  const title = document.createElement("span");
  title.className = "recording-title";
  title.textContent = item.title;
  const badge = document.createElement("span");
  badge.className = `recording-badge ${pending ? "is-pending" : "is-ready"}`;
  badge.textContent = pending ? "Pending" : "Ready";
  head.append(title, badge);

  const meta = document.createElement("span");
  meta.className = "recording-meta";
  meta.textContent = pending
    ? `${clockTime(item.created_at)} · Audio saved`
    : `${clockTime(item.created_at)} · ${formatTime(item.duration)} · ${peopleLabel(item.speaker_count)} · ${pairLabel(item)}`;

  const preview = document.createElement("span");
  preview.className = "recording-preview";
  preview.textContent = pending
    ? "Open and tap Transcribe when ready"
    : (item.preview || "No speech found — audio kept");

  button.append(head, meta, preview);
  button.addEventListener("click", () => openRecording(item.id));
  return button;
}
```

- [ ] **Step 2: Shorten empty state**

Where `#empty` text is set in HTML or JS, use:

`No recordings yet. Record or upload.`

- [ ] **Step 3: Manual check** — pending vs ready badges visible; banner shows during Working on library view.

- [ ] **Step 4: Commit only if user asked**

---

### Task 5: Visual refresh (dock / library / detail)

**Files:**
- Modify: `static/app.css`
- Modify: `static/index.html` only if class hooks missing
- Bump `?v=` cache busters

**Interfaces:**
- Consumes: classes from Tasks 2–4
- Produces: cohesive hierarchy without redesigning Settings

- [ ] **Step 1: Tokens + stage strip**

Add under `:root` (keep paper/accent family; small tweaks OK):

```css
:root {
  /* existing vars… */
  --stage-current: var(--accent);
  --badge-pending-bg: #f3e6d8;
  --badge-pending-ink: #7a4b1e;
  --badge-ready-bg: #e2efe9;
  --badge-ready-ink: #0f6e56;
}
```

```css
.stage-strip {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 0 0 6px;
  font: 600 0.72rem/1.2 ui-sans-serif, system-ui, sans-serif;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}

.stage-step {
  padding: 4px 8px;
  border-radius: 8px;
  border: 1px solid transparent;
}

.stage-step.is-current {
  color: var(--stage-current);
  border-color: color-mix(in srgb, var(--accent) 35%, var(--line));
  background: color-mix(in srgb, var(--accent) 10%, var(--card));
}

.stage-label:empty { display: none; }
.stage-label {
  margin: 0 0 8px;
  font: 0.9rem/1.35 ui-sans-serif, system-ui, sans-serif;
  color: var(--ink);
}

.library-job-banner {
  margin: 0 0 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--accent) 8%, var(--card));
  font: 0.92rem/1.35 ui-sans-serif, system-ui, sans-serif;
}

.library-job-banner[hidden] { display: none; }

.recording-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.recording-badge {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 999px;
  font: 600 0.7rem/1.2 ui-sans-serif, system-ui, sans-serif;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.recording-badge.is-pending {
  background: var(--badge-pending-bg);
  color: var(--badge-pending-ink);
}

.recording-badge.is-ready {
  background: var(--badge-ready-bg);
  color: var(--badge-ready-ink);
}

.detail-stage {
  margin: 0;
  font: 600 0.95rem/1.35 ui-sans-serif, system-ui, sans-serif;
  color: var(--ink);
}

.detail-stage:empty { display: none; }
```

- [ ] **Step 2: Dock hierarchy**

Adjust `#dock` so order reads: strip → label → progress → langs → **signal plane / mixer** → record row. Prefer CSS `display: flex; flex-direction: column; gap: …` and, while `body.is-recording`, ensure `.mixer-dock .signal-plane-wrap` is not collapsed (min-height ~96px). Increase `--dock` recording heights only if strip clips content.

- [ ] **Step 3: Detail hierarchy**

Tighten spacing so order is: title → **detail-stage** → langs/CTA → audio/mixer → transcript. Mute `#detail-meta` slightly vs stage line.

- [ ] **Step 4: Visual QA**

Desktop + narrow phone width: strip readable; badges not colliding with titles; plane visible while recording; Settings untouched visually.

- [ ] **Step 5: Commit only if user asked**

---

### Task 6: Verify + regression

**Files:**
- Touch none unless a bug fix is required

- [ ] **Step 1: Unit tests**

```bash
node --test tests/test_stage_model.mjs
```

Expected: PASS

- [ ] **Step 2: Python suite still green**

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Expected: existing tests PASS (no backend change required)

- [ ] **Step 3: Manual done-when checklist (from spec)**

- [ ] Record with live meter (grey/coral/green)
- [ ] Stop → Pending badge
- [ ] Transcribe → Working · … on strip + detail/banner
- [ ] Complete → Ready
- [ ] Soft fail keeps audio when already saved
- [ ] Offline / missing pack still requires Install consent (existing path)

- [ ] **Step 4: Commit only if user asked**

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Stage model single writer | 1, 3 |
| Dock strip Idle/Recording/Saving/Working | 2, 3, 5 |
| Item Pending/Ready/Failed | 1, 3, 4 |
| Live signal plane primary while recording | 5 (+ existing mixer) |
| Library badges + short empty | 4 |
| Detail status vocabulary | 3, 5 |
| Activity as input | 3 |
| Soft fail / offline honesty | 3 (wire) + 6 (manual) |
| Visual refresh dock/library/detail | 5 |
| No Settings/Android/TTS/new phases | Global constraints |

## Placeholder / consistency notes

- `StageModel.resolve` signatures in Task 1 match Task 3 `feedbackState`.
- Saving determinate progress: implement in Task 3 when retiring `showClientProgress` bar writes; keep tests in sync.
- Uncommitted local edits in `static/app.js` / `static/audio-mixer.js` must be reviewed before merge — fold or rebase carefully so signal-plane work is not lost.
