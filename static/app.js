const colors = ["#0f6e56", "#9a4d12", "#1d4e89", "#6b3fa0", "#8d2f23", "#3f6b2a"];

const settingsSheet = document.querySelector("#settings-sheet");
const openSettings = document.querySelector("#open-settings");
const modelSelect = document.querySelector("#model");
const customWrap = document.querySelector("#custom-wrap");
const customModel = document.querySelector("#custom-model");
const deviceSelect = document.querySelector("#device");
const computeSelect = document.querySelector("#compute-type");
const threadsInput = document.querySelector("#cpu-threads");
const thresholdInput = document.querySelector("#cluster-threshold");
const languageSelect = document.querySelector("#language");
const translateSelect = document.querySelector("#translate-to");
const swapButton = document.querySelector("#swap-languages");
const dockLanguage = document.querySelector("#dock-language");
const dockTranslate = document.querySelector("#dock-translate");
const detailLanguage = document.querySelector("#detail-language");
const detailTranslate = document.querySelector("#detail-translate");
const applyLanguages = document.querySelector("#apply-languages");
const settingsForm = document.querySelector("#settings-form");
const settingsStatus = document.querySelector("#settings-status");
const activeModel = document.querySelector("#active-model");
const libraryView = document.querySelector("#library-view");
const libraryList = document.querySelector("#library-list");
const libraryStatus = document.querySelector("#library-status");
const emptyNote = document.querySelector("#empty");
const searchInput = document.querySelector("#search");
const detailView = document.querySelector("#detail-view");
const backButton = document.querySelector("#back");
const deleteButton = document.querySelector("#delete");
const titleInput = document.querySelector("#title");
const detailMeta = document.querySelector("#detail-meta");
const player = document.querySelector("#player");
const detailStatus = document.querySelector("#detail-status");
const recordButton = document.querySelector("#record");
const stopButton = document.querySelector("#stop");
const fileInput = document.querySelector("#file");
const speakerSelect = document.querySelector("#num-speakers");
const timer = document.querySelector("#timer");
const micNote = document.querySelector("#mic-note");
const jobStatus = document.querySelector("#job-status");
const jobProgress = document.querySelector("#job-progress");
const jobTrack = document.querySelector("#job-progress-track");
const jobBar = document.querySelector("#job-progress-bar");
const jobProgressLabel = document.querySelector("#job-progress-label");
const cancelUploadButton = document.querySelector("#cancel-upload");
const detailProgress = document.querySelector("#detail-progress");
const detailTrack = document.querySelector("#detail-progress-track");
const detailBar = document.querySelector("#detail-progress-bar");
const detailProgressLabel = document.querySelector("#detail-progress-label");
const dock = document.querySelector("#dock");
const turnsList = document.querySelector("#turns");
const copyButton = document.querySelector("#copy");
const diarizationNote = document.querySelector("#diarization-note");
const emptyTranscript = document.querySelector("#empty-transcript");
const transcriptAudioSelect = document.querySelector("#transcript-audio");
const listenAudioSelect = document.querySelector("#listen-audio");
const dockMixerRoot = document.querySelector("#dock-mixer");
const detailMixerRoot = document.querySelector("#detail-mixer");
const page = document.querySelector("main");
const dialog = document.querySelector("#dialog");
const dialogTitle = document.querySelector("#dialog-title");
const dialogBody = document.querySelector("#dialog-body");
const dialogList = document.querySelector("#dialog-list");
const dialogActions = document.querySelector("#dialog-actions");
const dialogCancel = document.querySelector("#dialog-cancel");
const dialogConfirm = document.querySelector("#dialog-confirm");
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
  // True while a client job fetch is in flight (bridges /api/activity clear).
  clientJobActive: false,
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
  if (stageLabel) {
    const showLabel = out.flow !== "idle" || out.item === "failed";
    stageLabel.textContent = showLabel ? out.label : "";
  }

  const onDetail = document.body.classList.contains("is-detail");
  const box = onDetail ? detailProgress : jobProgress;
  const track = onDetail ? detailTrack : jobTrack;
  const bar = onDetail ? detailBar : jobBar;
  const labelEl = onDetail ? detailProgressLabel : jobProgressLabel;
  const otherBox = onDetail ? jobProgress : detailProgress;
  const otherTrack = onDetail ? jobTrack : detailTrack;
  const otherBar = onDetail ? jobBar : detailBar;
  if (otherBox && otherBar && otherTrack) {
    hideProgress(otherBox, otherBar, otherTrack, { clearCancel: false });
  }

  if (out.progress.mode === "hidden") {
    if (box && bar && track) hideProgress(box, bar, track);
    document.body.classList.remove("is-downloading");
  } else if (box && bar && track && labelEl) {
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
      detailStage.textContent = feedbackState.itemPending === true
        ? "Pending — audio saved. Tap Transcribe when ready."
        : (out.label || "Pending — no speech found, audio kept");
    } else if (out.item === "ready") detailStage.textContent = "Ready";
    else detailStage.textContent = "";
  }

  // Stage chrome owns recording, saving, working, and failed. Leave idle
  // status lines (copy, settings, cancel) alone.
  if (out.flow !== "idle" || out.item === "failed") {
    if (!onDetail && jobStatus) jobStatus.textContent = "";
    else if (detailStatus) detailStatus.textContent = "";
  }
}

let presets = [];
let recorder = null;
let chunks = [];
let timerId = 0;
let startedAt = 0;
let wakeLock = null;
let searchTimer = 0;
let turns = [];
let diarizationError = "";
let currentId = "";
let savedLanguage = "en";
let savedTranslate = "";
let savedModel = "";
let catalog = { speech: {}, pairs: [], multilingual: {} };
let watchTimer = 0;
let watchGeneration = 0;
let highlightFrame = 0;
let dialogResolver = null;
let dialogReturn = null;
let gateOpen = false;
let downloadsLoaded = false;
let liveMixer = null;
let liveMicStream = null;
let mixerSettings = AudioMixer.loadSettings();
let previewUrl = "";
let previewBlob = null;
let hasCleaned = false;
let transcriptAudio = "original";
let originalAudioUrl = "";
let cleanedAudioUrl = "";
let recordingPending = false;
let uploadCancelled = false;
let activeUploadXhr = null;
let activeUploadId = "";
const speakerNames = new Map();
const mixerViews = new Map();

mountMixer(dockMixerRoot, "dock");
mountMixer(detailMixerRoot, "detail");
syncMixerViews();

if (transcriptAudioSelect) {
  transcriptAudioSelect.addEventListener("change", async () => {
    if (!currentId) return;
    const response = await fetch(`/api/recordings/${currentId}/transcript-audio`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_source: transcriptAudioSelect.value }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      await ask({
        title: "Could not set transcript audio",
        body: messageFrom(payload, "Choose original or a saved cleaned file."),
        cancelLabel: "Close",
      });
      transcriptAudioSelect.value = transcriptAudio;
      return;
    }
    applyRecordingPayload(payload);
  });
}

if (listenAudioSelect) {
  listenAudioSelect.addEventListener("change", () => {
    refreshPlayerSource();
  });
}

openSettings.addEventListener("click", () => {
  settingsSheet.hidden = !settingsSheet.hidden;
  openSettings.textContent = settingsSheet.hidden ? "Settings" : "Close";
  if (!settingsSheet.hidden) refreshDownloads();
});

modelSelect.addEventListener("change", () => {
  customWrap.hidden = modelSelect.value !== "custom";
  paintMarks();
});

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveSettings();
});

swapButton.addEventListener("click", () => {
  const spoken = languageSelect.value;
  const reading = translateSelect.value;
  if (spoken === "auto" || reading === "off") return;
  languageSelect.value = reading;
  translateSelect.value = spoken;
  syncDock();
});

for (const select of [languageSelect, translateSelect]) {
  select.addEventListener("change", () => {
    syncDock();
    paintMarks();
  });
}

for (const select of [dockLanguage, dockTranslate]) {
  select.addEventListener("change", () => {
    languageSelect.value = dockLanguage.value;
    translateSelect.value = dockTranslate.value;
    paintMarks();
    saveSettings();
  });
}

detailLanguage.addEventListener("change", () => {
  refreshLanguageAction();
  paintMarks();
});
detailTranslate.addEventListener("change", refreshLanguageAction);
applyLanguages.addEventListener("click", applyRecordingLanguages);

searchInput.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => loadLibrary(searchInput.value), 200);
});

backButton.addEventListener("click", showLibrary);
deleteButton.addEventListener("click", deleteCurrent);
titleInput.addEventListener("input", sizeTitle);
titleInput.addEventListener("change", persistDetail);
copyButton.addEventListener("click", copyTranscript);
recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", () => {
  if (recorder && recorder.state !== "inactive") recorder.stop();
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (file) acceptAudio(file, file.name);
});

document.body.addEventListener("dragover", (event) => event.preventDefault());
document.body.addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer && event.dataTransfer.files[0];
  if (file) acceptAudio(file, file.name);
});

dialogCancel.addEventListener("click", () => closeDialog(false));
dialogConfirm.addEventListener("click", () => closeDialog(true));
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) closeDialog(false);
});
dialog.addEventListener("keydown", onDialogKey);
if (cancelUploadButton) {
  cancelUploadButton.addEventListener("click", () => cancelActiveUpload());
}

player.addEventListener("timeupdate", highlightCurrentTurn);
player.addEventListener("seeked", highlightCurrentTurn);
player.addEventListener("play", trackSpeech);
player.addEventListener("pause", () => cancelAnimationFrame(highlightFrame));
player.addEventListener("ended", () => cancelAnimationFrame(highlightFrame));

if (!window.isSecureContext) {
  micNote.hidden = false;
  micNote.textContent = "This address cannot use the microphone. Open localhost on this computer, or the HTTPS address and trust the certificate. Upload still works.";
}

loadSettings();
loadLibrary("");
reclaimFinishedUploads();

async function reclaimFinishedUploads() {
  // Any fully uploaded file still in staging becomes a library item automatically.
  try {
    const payload = await fetchJson("/api/uploads/pending");
    const finished = (payload.uploads || []).filter((item) => item.complete);
    if (finished.length === 0) return;
    let lastId = "";
    for (const item of finished) {
      const body = new FormData();
      body.append("num_speakers", speakerSelect ? speakerSelect.value : "auto");
      const saved = await fetchJson(`/api/uploads/${item.id}/save`, {
        method: "POST",
        body,
      });
      lastId = saved && saved.id ? saved.id : lastId;
    }
    await loadLibrary(searchInput ? searchInput.value : "");
    if (lastId && libraryView && !libraryView.hidden) {
      jobStatus.textContent = "Saved an upload that was already on this computer.";
    }
  } catch (_error) {
    // Page still works; user can re-select the file to resume/save.
  }
}

async function loadSettings() {
  const [response, downloads] = await Promise.all([
    fetch("/api/settings"),
    fetch("/api/downloads"),
  ]);
  if (!response.ok) {
    activeModel.textContent = "Settings could not be loaded.";
    return;
  }
  if (downloads.ok) {
    catalog = await downloads.json();
    downloadsLoaded = true;
  }
  const payload = await response.json();
  presets = payload.presets;
  fillSelect(modelSelect, payload.presets);
  const custom = document.createElement("option");
  custom.value = "custom";
  custom.dataset.name = "Other model or folder";
  custom.textContent = "Other model or folder";
  modelSelect.appendChild(custom);
  fillSelect(deviceSelect, payload.devices);
  fillSelect(computeSelect, payload.compute_types);
  fillLanguages(languageSelect, payload.spoken_languages);
  fillLanguages(dockLanguage, payload.spoken_languages);
  fillLanguages(detailLanguage, payload.spoken_languages);
  fillLanguages(translateSelect, payload.translate_languages);
  fillLanguages(dockTranslate, payload.translate_languages);
  fillLanguages(detailTranslate, payload.translate_languages);
  applySettings(payload.settings, payload.resolved || null);
}

function fillLanguages(select, values) {
  select.replaceChildren();
  for (const item of values) {
    const option = document.createElement("option");
    option.value = item.code;
    option.dataset.name = item.name;
    option.textContent = item.name;
    select.appendChild(option);
  }
}

function fillSelect(select, values) {
  select.replaceChildren();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.dataset.name = value;
    option.textContent = value;
    select.appendChild(option);
  }
}

function applySettings(settings, resolved) {
  savedModel = settings.model;
  if (presets.includes(settings.model)) {
    modelSelect.value = settings.model;
    customModel.value = "";
    customWrap.hidden = true;
  } else {
    modelSelect.value = "custom";
    customModel.value = settings.model;
    customWrap.hidden = false;
  }
  deviceSelect.value = settings.device;
  computeSelect.value = settings.compute_type;
  threadsInput.value = String(settings.cpu_threads);
  thresholdInput.value = String(settings.cluster_threshold);
  languageSelect.value = settings.language || "en";
  translateSelect.value = settings.translate_to || "off";
  syncDock();
  paintMarks();
  const backend = resolved && resolved.device ? resolved.device : settings.device;
  const compute = resolved && resolved.compute_type
    ? resolved.compute_type
    : settings.compute_type;
  if (settings.device === "auto" && backend !== "auto") {
    activeModel.textContent = `${settings.model} on ${backend} (auto), ${compute}`;
  } else {
    activeModel.textContent = `${settings.model} on ${backend}, ${compute}`;
  }
}

function syncDock() {
  dockLanguage.value = languageSelect.value;
  dockTranslate.value = translateSelect.value;
}

function chosenModel() {
  if (modelSelect.value === "custom") return customModel.value.trim();
  return modelSelect.value;
}

async function saveSettings(options = {}) {
  const quiet = options.quiet === true;
  if (!quiet) settingsStatus.textContent = "Saving…";
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: chosenModel(),
      device: deviceSelect.value,
      compute_type: computeSelect.value,
      cpu_threads: Number(threadsInput.value),
      cluster_threshold: Number(thresholdInput.value),
      language: languageSelect.value,
      translate_to: translateSelect.value === "off" ? "" : translateSelect.value,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = messageFrom(payload, "Settings were not saved.");
    if (quiet) {
      await ask({
        title: "Settings were not saved",
        body: message,
        cancelLabel: "Close",
      });
    } else {
      settingsStatus.textContent = message;
    }
    return false;
  }
  applySettings(payload, payload.resolved || null);
  if (!quiet) settingsStatus.textContent = "Saved. The next transcription uses this.";
  return true;
}

async function loadLibrary(query) {
  const response = await fetch(`/api/recordings?q=${encodeURIComponent(query)}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    libraryStatus.textContent = messageFrom(payload, "Recordings could not be loaded.");
    return;
  }
  libraryStatus.textContent = "";
  const recordings = payload.recordings || [];
  emptyNote.hidden = recordings.length > 0 || query.trim() !== "";
  libraryList.replaceChildren();
  if (recordings.length === 0 && query.trim()) {
    const note = document.createElement("p");
    note.className = "empty";
    note.textContent = "No recordings match that search.";
    libraryList.appendChild(note);
    return;
  }
  let lastDay = "";
  let card = null;
  for (const item of recordings) {
    const day = dayLabel(item.created_at);
    if (day !== lastDay) {
      const block = document.createElement("section");
      block.className = "day";
      const heading = document.createElement("h2");
      heading.className = "day-label";
      heading.textContent = day;
      card = document.createElement("div");
      card.className = "day-card";
      block.append(heading, card);
      libraryList.appendChild(block);
      lastDay = day;
    }
    card.appendChild(renderRecording(item));
  }
}

function renderRecording(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "recording";
  const awaitingTranscript = Boolean(item.pending || item.status === "pending");
  // Empty preview after a finished job = no usable transcript → Pending badge.
  const noSpeech = !awaitingTranscript && !String(item.preview || "").trim();
  const pending = awaitingTranscript || noSpeech;

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
  meta.textContent = awaitingTranscript
    ? `${clockTime(item.created_at)} · Audio saved`
    : `${clockTime(item.created_at)} · ${formatTime(item.duration)} · ${peopleLabel(item.speaker_count)} · ${pairLabel(item)}`;

  const preview = document.createElement("span");
  preview.className = "recording-preview";
  preview.textContent = awaitingTranscript
    ? "Open and tap Transcribe when ready"
    : (item.preview || "No speech found — audio kept");

  button.append(head, meta, preview);
  button.addEventListener("click", () => openRecording(item.id));
  return button;
}

function peopleLabel(count) {
  if (count === 1) return "1 speaker";
  return `${count} speakers`;
}

async function openRecording(recordingId) {
  const response = await fetch(`/api/recordings/${recordingId}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    libraryStatus.textContent = messageFrom(payload, "That recording could not be opened.");
    return;
  }
  clearPreview();
  applyRecordingPayload(payload);
  libraryView.hidden = true;
  detailView.hidden = false;
  dock.hidden = true;
  document.body.classList.add("is-detail");
  settingsSheet.hidden = true;
  openSettings.textContent = "Settings";
  paintFeedback();
}

function applyRecordingPayload(payload) {
  currentId = payload.id;
  savedLanguage = payload.language || "en";
  savedTranslate = payload.translate_to || "";
  savedModel = payload.model || savedModel;
  hasCleaned = Boolean(payload.has_cleaned);
  transcriptAudio = payload.transcript_audio || "original";
  originalAudioUrl = payload.audio_url || "";
  cleanedAudioUrl = payload.cleaned_audio_url || "";
  detailLanguage.value = savedLanguage;
  detailTranslate.value = savedTranslate || "off";
  if (transcriptAudioSelect) {
    transcriptAudioSelect.value = transcriptAudio;
    const cleanedOption = transcriptAudioSelect.querySelector('option[value="cleaned"]');
    if (cleanedOption) {
      cleanedOption.disabled = !hasCleaned;
      cleanedOption.textContent = hasCleaned ? "Cleaned" : "Cleaned (not saved)";
    }
  }
  if (listenAudioSelect) {
    const cleanedOpt = listenAudioSelect.querySelector('option[value="cleaned"]');
    const previewOpt = listenAudioSelect.querySelector('option[value="preview"]');
    if (cleanedOpt) cleanedOpt.disabled = !hasCleaned;
    if (previewOpt) previewOpt.disabled = !previewUrl;
    if (previewUrl) listenAudioSelect.value = "preview";
    else if (transcriptAudio === "cleaned" && hasCleaned) listenAudioSelect.value = "cleaned";
    else listenAudioSelect.value = "original";
  }
  recordingPending = Boolean(payload.pending || payload.status === "pending");
  refreshLanguageAction();
  titleInput.value = payload.title;
  sizeTitle();
  const pending = recordingPending;
  detailMeta.textContent = pending
    ? `${dayLabel(payload.created_at)} · ${clockTime(payload.created_at)} · Not transcribed yet`
    : `${dayLabel(payload.created_at)} · ${clockTime(payload.created_at)} · ${formatTime(payload.duration)} · ${pairLabel(payload)} · ${payload.model}`;
  refreshPlayerSource();
  detailStatus.textContent = "";
  speakerNames.clear();
  for (const [speaker, name] of Object.entries(payload.speaker_names || {})) {
    speakerNames.set(Number(speaker), name);
  }
  renderTranscript(payload);
  const transcriptTurns = payload.turns || payload.segments || [];
  setFeedback({
    itemPending: Boolean(recordingPending),
    hasTranscript: Boolean(transcriptTurns.length),
    failed: false,
    failMessage: "",
  });
  updateDetailMixerActions();
  // Paint the original waveform immediately; filter preview updates colors later.
  requestAnimationFrame(() => {
    const plane = mixerViews.get("detail")?.els.plane;
    if (plane) plane.redraw();
    paintDetailOriginalPlane();
  });
  scheduleDetailClean();
}

function refreshPlayerSource() {
  const choice = listenAudioSelect ? listenAudioSelect.value : "original";
  if (choice === "preview" && previewUrl) player.src = previewUrl;
  else if (choice === "cleaned" && cleanedAudioUrl) player.src = cleanedAudioUrl;
  else player.src = originalAudioUrl;
}

function clearPreview() {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = "";
  previewBlob = null;
}

function showLibrary() {
  player.pause();
  detailPlaneToken += 1;
  detailView.hidden = true;
  libraryView.hidden = false;
  dock.hidden = false;
  document.body.classList.remove("is-detail");
  setFeedback({ itemPending: null, hasTranscript: false });
  const detailPlane = mixerViews.get("detail")?.els.plane;
  if (detailPlane) detailPlane.idle();
  loadLibrary(searchInput.value);
}

async function deleteCurrent() {
  if (!currentId) return;
  const agreed = await ask({
    title: "Delete this recording?",
    body: "The audio and the transcript are removed from this computer.",
    confirmLabel: "Delete",
    cancelLabel: "Keep it",
    tone: "danger",
  });
  if (!agreed) return;
  const response = await fetch(`/api/recordings/${currentId}`, { method: "DELETE" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    await ask({
      title: "This recording was not deleted",
      body: messageFrom(payload, "The recording was not deleted."),
      cancelLabel: "Close",
    });
    return;
  }
  currentId = "";
  showLibrary();
}

async function persistDetail() {
  if (!currentId) return;
  const response = await fetch(`/api/recordings/${currentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: titleInput.value,
      speaker_names: Object.fromEntries(speakerNames),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    detailStatus.textContent = messageFrom(payload, "The change was not saved.");
    return;
  }
  titleInput.value = payload.title;
  sizeTitle();
  detailStatus.textContent = "Saved.";
}

async function acceptAudio(file, filename) {
  // Models are only needed when the user taps Transcribe later.
  transcribeBlob(file, filename);
}

async function startRecording() {
  const language = dockLanguage.value;
  const translateTo = dockTranslate.value;
  const model = chosenModel();
  const knownReady = downloadsLoaded
    && missingPieces(language, translateTo, model).kind === "ready";
  if (!knownReady) {
    const outcome = await prepareModels({
      language,
      translateTo,
      model,
      persist: true,
      when: "before recording",
      watch: "job",
    });
    if (outcome === "installed") {
      jobStatus.textContent = "Installed. Tap Record to start.";
      return;
    }
    if (outcome !== "ready") return;
  }
  showLibrary();
  jobStatus.textContent = "";
  try {
    liveMicStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    });
    const monitor = Boolean(mixerViews.get("dock")?.els.monitor?.checked);
    liveMixer = AudioMixer.createLiveSession(liveMicStream, mixerSettings, {
      monitor,
      onLevel(level, gainValue) {
        paintMixerLevel("dock", level, gainValue);
      },
      onFrame(frame) {
        paintSignalPlane("dock", frame);
      },
    });
    document.body.classList.add("is-recording");
    const mimeType = pickMime();
    const options = { audioBitsPerSecond: 32000 };
    if (mimeType) options.mimeType = mimeType;
    chunks = [];
    recorder = new MediaRecorder(liveMixer.stream, options);
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });
    recorder.addEventListener("stop", async () => {
      document.body.classList.remove("is-recording");
      if (liveMicStream) liveMicStream.getTracks().forEach((track) => track.stop());
      liveMicStream = null;
      if (liveMixer) await liveMixer.stop();
      liveMixer = null;
      paintMixerLevel("dock", { rms: 0, peak: 0 }, mixerSettings.gain);
      const dockView = mixerViews.get("dock");
      if (dockView && dockView.els.plane) dockView.els.plane.idle();
      releaseWakeLock();
      stopTimer();
      const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" });
      const extension = blob.type.includes("mp4") ? "m4a" : "webm";
      setFeedback({
        recording: false,
        saving: true,
        failed: false,
        failMessage: "",
        received: 0,
        total: 0,
      });
      transcribeBlob(blob, `recording.${extension}`);
    });
    recorder.start();
    recordButton.hidden = true;
    stopButton.hidden = false;
    timer.hidden = false;
    startedAt = Date.now();
    tick();
    timerId = window.setInterval(tick, 500);
    setFeedback({ recording: true, failed: false, failMessage: "" });
    await requestWakeLock();
  } catch (_error) {
    document.body.classList.remove("is-recording");
    setFeedback({ recording: false });
    if (liveMicStream) liveMicStream.getTracks().forEach((track) => track.stop());
    liveMicStream = null;
    if (liveMixer) {
      liveMixer.stop();
      liveMixer = null;
    }
    await ask({
      title: "The microphone did not start",
      body: "You can still upload a recording. On a phone, use the HTTPS address "
        + "and trust the certificate.",
      cancelLabel: "Close",
    });
  }
}

function pickMime() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function tick() {
  timer.textContent = formatTime((Date.now() - startedAt) / 1000);
}

function stopTimer() {
  window.clearInterval(timerId);
  timer.hidden = true;
  recordButton.hidden = false;
  stopButton.hidden = true;
}

async function requestWakeLock() {
  if (!navigator.wakeLock) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
  } catch (_error) {
    wakeLock = null;
  }
}

function releaseWakeLock() {
  if (wakeLock) wakeLock.release();
  wakeLock = null;
}

async function transcribeBlob(blob, filename) {
  showLibrary();
  setBusy(true);
  uploadCancelled = false;
  activeUploadId = "";
  setCancelUploadVisible(true);
  await requestWakeLock();
  showClientProgress(0, blob.size || 0, "Uploading");
  try {
    const payload = blob.size > 256 * 1024
      ? await uploadChunkedToLibrary(blob, filename)
      : await uploadToLibrary(blob, filename);
    throwIfUploadCancelled();
    setCancelUploadVisible(false);
    setFeedback({
      saving: false,
      itemPending: true,
      hasTranscript: false,
      failed: false,
      failMessage: "",
      activityActive: false,
      activityPhase: "",
      activityLabel: "",
      received: 0,
      total: 0,
    });
    searchInput.value = "";
    await openRecording(payload.id);
  } catch (error) {
    setCancelUploadVisible(false);
    if (error && error.name === "AbortError") {
      setFeedback({
        saving: false,
        failed: false,
        failMessage: "",
        activityActive: false,
        activityPhase: "",
        activityLabel: "",
        received: 0,
        total: 0,
      });
      jobStatus.textContent = "Upload cancelled. Already sent parts are kept if you retry the same file.";
      return;
    }
    const lost = error && error.name === "NetworkError";
    setFeedback({
      saving: false,
      failed: true,
      failMessage: (error && error.message) || "Upload failed — try again",
      activityActive: false,
      activityPhase: "",
      activityLabel: "",
      received: 0,
      total: 0,
    });
    await ask({
      title: "Upload did not finish",
      body: lost
        ? "Connection stayed down too long. Keep this screen open and tap Upload again with the same file — finished parts are kept and it continues from there."
        : String((error && error.message) || "Upload failed."),
      cancelLabel: "Close",
    });
  } finally {
    stopWatch();
    releaseWakeLock();
    setBusy(false);
    setCancelUploadVisible(false);
    activeUploadXhr = null;
    activeUploadId = "";
    refreshDownloads();
  }
}

function setCancelUploadVisible(visible) {
  if (!cancelUploadButton) return;
  cancelUploadButton.hidden = !visible;
}

function cancelActiveUpload() {
  uploadCancelled = true;
  if (activeUploadXhr) {
    try {
      activeUploadXhr.abort();
    } catch (_error) {
      // Ignore abort races.
    }
  }
  // Keep uploaded chunks on disk for resume; only abort the in-flight request.
}

function throwIfUploadCancelled() {
  if (!uploadCancelled) return;
  const error = new Error("Upload cancelled.");
  error.name = "AbortError";
  throw error;
}

// Sparse DOM updates only — does not throttle the network transfer itself.
const PROGRESS_UI_MS = 2500;

function showClientProgress(loaded, total, label, force) {
  const now = Date.now();
  if (!force && showClientProgress._lastAt && now - showClientProgress._lastAt < PROGRESS_UI_MS) {
    showClientProgress._pending = { loaded, total, label };
    if (!showClientProgress._timer) {
      showClientProgress._timer = window.setTimeout(() => {
        showClientProgress._timer = 0;
        const pending = showClientProgress._pending;
        showClientProgress._pending = null;
        if (pending) showClientProgress(pending.loaded, pending.total, pending.label, true);
      }, PROGRESS_UI_MS - (now - showClientProgress._lastAt));
    }
    return;
  }
  showClientProgress._lastAt = now;
  showClientProgress._pending = null;
  if (showClientProgress._timer) {
    window.clearTimeout(showClientProgress._timer);
    showClientProgress._timer = 0;
  }
  if (cancelUploadButton && !uploadCancelled) cancelUploadButton.hidden = false;
  const safeTotal = Number(total) || 0;
  const safeLoaded = Number(loaded) || 0;
  // Callers still pass Uploading / Resuming / Reconnecting as `label`. The
  // visible text comes from StageModel; the word only guards activity polls.
  setFeedback({
    saving: true,
    failed: false,
    failMessage: "",
    activityLabel: String(label || ""),
    received: safeLoaded,
    total: safeTotal,
  });
}

function fileFingerprint(blob, filename) {
  // Name + size only — Android often changes lastModified when re-picking.
  const name = filename || blob.name || "audio";
  return `${name}|${blob.size || 0}`;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function uploadChunkedToLibrary(blob, filename) {
  throwIfUploadCancelled();
  const fingerprint = fileFingerprint(blob, filename);
  const created = await fetchJson("/api/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: filename || blob.name || "audio.webm",
      size: blob.size,
      fingerprint,
    }),
  });
  throwIfUploadCancelled();
  if (created.already_in_library && created.recording) {
    showClientProgress(blob.size, blob.size, "Already in your library", true);
    return created.recording;
  }
  activeUploadId = created.id || "";
  const chunkSize = Number(created.chunk_size) || (8 * 1024 * 1024);
  const totalChunks = Number(created.total_chunks) || Math.ceil(blob.size / chunkSize) || 1;
  const received = new Set(
    (created.received || []).map((value) => Number(value)),
  );
  let confirmedBytes = Number(created.bytes_received) || 0;
  if (created.complete) {
    showClientProgress(blob.size, blob.size, "Already on this computer", true);
  } else if (confirmedBytes > 0) {
    showClientProgress(confirmedBytes, blob.size, "Resuming upload", true);
  } else {
    showClientProgress(0, blob.size, "Uploading", true);
  }

  // One stream is fastest on phone/Tailscale. Parallel chunks fight for the uplink
  // and often trigger timeouts/retries that make a 55 MB file take many minutes.
  for (let index = 0; index < totalChunks; index += 1) {
    throwIfUploadCancelled();
    if (received.has(index)) continue;
    const start = index * chunkSize;
    const end = Math.min(blob.size, start + chunkSize);
    const slice = blob.slice(start, end);
    const status = await putChunkWithRetry(
      created.id,
      index,
      slice,
      blob.size,
      () => confirmedBytes,
    );
    for (const value of status.received || []) received.add(Number(value));
    confirmedBytes = Number(status.bytes_received) || Math.min(blob.size, confirmedBytes + slice.size);
    showClientProgress(confirmedBytes, blob.size, "Uploading", true);
  }

  throwIfUploadCancelled();
  showClientProgress(blob.size, blob.size, "Uploaded", true);
  return fetchJson(`/api/uploads/${created.id}/save`, {
    method: "POST",
    body: (() => {
      const body = new FormData();
      body.append("num_speakers", speakerSelect.value);
      return body;
    })(),
  });
}

async function putChunkWithRetry(uploadId, index, slice, totalSize, confirmedBytes) {
  let attempt = 0;
  let delay = 500;
  // Keep retrying through short Tailscale/Wi‑Fi drops without forcing a re-pick.
  while (attempt < 40) {
    throwIfUploadCancelled();
    attempt += 1;
    const base = typeof confirmedBytes === "function" ? confirmedBytes() : confirmedBytes;
    try {
      return await putChunk(uploadId, index, slice, (sentInChunk) => {
        showClientProgress(
          Math.min(totalSize, base + sentInChunk),
          totalSize,
          attempt > 1 ? `Reconnecting · chunk ${index + 1}` : "Uploading",
        );
      });
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      const network = !error || error.name === "NetworkError";
      if (!network || attempt >= 40) throw error;
      showClientProgress(base, totalSize, `Connection blip — retry ${attempt}/40`, true);
      await sleep(delay);
      delay = Math.min(8000, Math.round(delay * 1.4));
    }
  }
  const error = new Error("Could not upload that chunk.");
  error.name = "NetworkError";
  throw error;
}

function putChunk(uploadId, index, slice, onProgress) {
  return new Promise((resolve, reject) => {
    throwIfUploadCancelled();
    const xhr = new XMLHttpRequest();
    activeUploadXhr = xhr;
    xhr.open("PUT", `/api/uploads/${uploadId}/chunks/${index}`);
    xhr.responseType = "json";
    // Large chunks over a phone VPN can take a while; abort only if truly stuck.
    xhr.timeout = 300000;
    xhr.upload.onprogress = (event) => {
      if (typeof onProgress !== "function") return;
      const loaded = event.lengthComputable ? event.loaded : 0;
      if (loaded > 0) onProgress(loaded);
    };
    xhr.onload = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const payload = xhr.response && typeof xhr.response === "object" ? xhr.response : {};
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
        return;
      }
      const error = new Error(
        typeof payload.detail === "string" ? payload.detail : `Chunk upload failed (${xhr.status}).`,
      );
      error.name = xhr.status >= 500 || xhr.status === 0 ? "NetworkError" : "ServerError";
      reject(error);
    };
    xhr.onerror = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const error = new Error("The page lost contact while uploading a chunk.");
      error.name = "NetworkError";
      reject(error);
    };
    xhr.ontimeout = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const error = new Error("A chunk upload timed out.");
      error.name = "NetworkError";
      reject(error);
    };
    xhr.onabort = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const error = new Error("Upload cancelled.");
      error.name = "AbortError";
      reject(error);
    };
    xhr.send(slice);
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      typeof payload.detail === "string" ? payload.detail : `Request failed (${response.status}).`,
    );
    error.name = response.status >= 500 ? "NetworkError" : "ServerError";
    throw error;
  }
  return payload;
}

function uploadToLibrary(blob, filename) {
  return new Promise((resolve, reject) => {
    throwIfUploadCancelled();
    const body = new FormData();
    body.append("audio", blob, filename);
    body.append("num_speakers", speakerSelect.value);
    const xhr = new XMLHttpRequest();
    activeUploadXhr = xhr;
    let uploadDone = false;

    xhr.open("POST", "/api/recordings");
    xhr.responseType = "json";
    xhr.timeout = 0;

    xhr.upload.onprogress = (event) => {
      showClientProgress(
        event.loaded,
        event.lengthComputable ? event.total : blob.size,
        "Uploading",
      );
    };

    xhr.upload.onload = () => {
      uploadDone = true;
      showClientProgress(blob.size || 1, blob.size || 1, "Uploaded", true);
    };

    xhr.onload = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const payload = xhr.response && typeof xhr.response === "object"
        ? xhr.response
        : {};
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
        return;
      }
      const detail = typeof payload.detail === "string"
        ? payload.detail
        : `Server returned ${xhr.status}.`;
      const error = new Error(detail);
      error.name = "ServerError";
      reject(error);
    };

    xhr.onerror = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const error = new Error("The page lost contact with this computer.");
      error.name = "NetworkError";
      reject(error);
    };

    xhr.ontimeout = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const error = new Error("The upload timed out.");
      error.name = "NetworkError";
      reject(error);
    };

    xhr.onabort = () => {
      if (activeUploadXhr === xhr) activeUploadXhr = null;
      const error = new Error("Upload cancelled.");
      error.name = "AbortError";
      reject(error);
    };

    xhr.onloadstart = () => {
      window.setTimeout(() => {
        if (!uploadDone && xhr.readyState < 4) {
          showClientProgress(0, blob.size || 0, "Uploading");
        }
      }, 0);
    };

    xhr.send(body);
  });
}


function setBusy(busy) {
  recordButton.dataset.forceBusy = busy ? "1" : "";
  applyLanguages.dataset.forceBusy = busy ? "1" : "";
  recordButton.disabled = busy;
  fileInput.disabled = busy;
  speakerSelect.disabled = busy;
  if (!busy) refreshRunAvailability();
  else applyLanguages.disabled = true;
}

function renderTranscript(payload) {
  turns = payload.turns || [];
  if ("diarization_error" in payload) diarizationError = payload.diarization_error || "";
  if (diarizationError) {
    diarizationNote.hidden = false;
    diarizationNote.textContent = `Speaker labels were unavailable. ${diarizationError}`;
  } else {
    diarizationNote.hidden = true;
    diarizationNote.textContent = "";
  }
  const pending = Boolean(payload.pending || payload.status === "pending");
  recordingPending = pending;
  emptyTranscript.hidden = turns.length > 0;
  if (!emptyTranscript.hidden) {
    emptyTranscript.textContent = pending
      ? "Audio is saved. Choose languages if you want, then tap Transcribe."
      : "No speech was found in this recording. The audio is kept — try the mixer "
        + "(Speaker preset), save cleaned audio, then Transcribe again.";
  }
  copyButton.hidden = turns.length === 0;
  turnsList.replaceChildren();
  for (const turn of turns) turnsList.appendChild(renderTurn(turn));
}

function renderTurn(turn) {
  const item = document.createElement("li");
  item.className = "turn";
  item.dataset.start = String(turn.start);
  item.dataset.end = String(turn.end);
  const swatch = document.createElement("div");
  swatch.className = "swatch";
  swatch.style.background = colors[speakerPlace(turn.speaker) % colors.length];
  const body = document.createElement("div");
  body.className = "turn-body";
  const speaker = document.createElement("div");
  speaker.className = "speaker";
  const nameButton = document.createElement("button");
  nameButton.type = "button";
  nameButton.textContent = nameFor(turn.speaker);
  nameButton.addEventListener("click", (event) => {
    event.stopPropagation();
    renameSpeaker(turn.speaker, nameButton);
  });
  const time = document.createElement("span");
  time.className = "time";
  time.textContent = formatTime(turn.start);
  speaker.append(nameButton, time);
  if (turn.translation) {
    const translation = document.createElement("p");
    translation.className = "translation";
    translation.textContent = turn.translation;
    body.append(speaker, translation, renderSpoken(turn, true));
  } else {
    body.append(speaker, renderSpoken(turn, false));
  }
  item.append(swatch, body);
  item.addEventListener("click", () => {
    player.currentTime = turn.start;
    player.play();
  });
  return item;
}

function renderSpoken(turn, isOriginal) {
  const paragraph = document.createElement("p");
  if (isOriginal) paragraph.className = "original is-source";
  const pieces = spokenPieces(turn);
  pieces.forEach((piece, index) => {
    if (index > 0) paragraph.append(" ");
    const word = document.createElement("span");
    word.className = "word";
    word.dataset.start = String(piece.start);
    word.dataset.end = String(piece.end);
    word.textContent = piece.word;
    word.addEventListener("click", (event) => {
      event.stopPropagation();
      player.currentTime = piece.start;
      player.play();
    });
    paragraph.append(word);
  });
  return paragraph;
}

function spokenPieces(turn) {
  const words = String(turn.text || "").match(/\S+/g) || [];
  const start = Number(turn.start) || 0;
  const end = Math.max(start, Number(turn.end) || start);
  const span = Math.max(end - start, 0.05);
  if (words.length === 0) return [];
  return words.map((word, index) => ({
    word,
    start: start + (span * index) / words.length,
    end: start + (span * (index + 1)) / words.length,
  }));
}

function trackSpeech() {
  highlightCurrentTurn();
  if (!player.paused && !player.ended) {
    highlightFrame = window.requestAnimationFrame(trackSpeech);
  }
}

function highlightCurrentTurn() {
  const time = player.currentTime;
  let activeTurn = null;
  for (const item of turnsList.children) {
    const start = Number(item.dataset.start);
    const end = Number(item.dataset.end);
    const current = time >= start && time < end;
    if (current && !item.classList.contains("is-current")) activeTurn = item;
    item.classList.toggle("is-current", current);
    const words = item.querySelectorAll(".word");
    words.forEach((word, index) => {
      const wordStart = Number(word.dataset.start);
      const wordEnd = Number(word.dataset.end);
      const last = index === words.length - 1;
      const spoken = current && time >= wordStart && (time < wordEnd || last);
      word.classList.toggle("is-spoken", spoken);
    });
  }
  if (activeTurn) activeTurn.scrollIntoView({ block: "nearest" });
}

function speakerPlace(speaker) {
  const ids = [];
  for (const turn of turns) {
    if (!ids.includes(turn.speaker)) ids.push(turn.speaker);
  }
  const place = ids.indexOf(speaker);
  return place === -1 ? speaker : place;
}

function nameFor(speaker) {
  return speakerNames.get(speaker) || `Speaker ${speakerPlace(speaker) + 1}`;
}

function sizeTitle() {
  titleInput.style.height = "auto";
  titleInput.style.height = `${titleInput.scrollHeight}px`;
}

function renameSpeaker(speaker, button) {
  const input = document.createElement("input");
  input.className = "rename";
  input.value = nameFor(speaker);
  input.setAttribute("aria-label", "Speaker name");
  button.replaceWith(input);
  input.focus();
  input.select();
  let finished = false;
  const commit = () => {
    if (finished) return;
    finished = true;
    const next = input.value.trim();
    if (next) speakerNames.set(speaker, next);
    renderTranscript({ turns });
    persistDetail();
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") input.blur();
    if (event.key === "Escape") {
      input.value = nameFor(speaker);
      input.blur();
    }
  });
  input.addEventListener("blur", commit);
}

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = String(total % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

function dayLabel(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const day = new Date(date);
  day.setHours(0, 0, 0, 0);
  const diff = Math.round((start - day) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff > 1 && diff < 7) return date.toLocaleDateString(undefined, { weekday: "long" });
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function clockTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function pairLabel(item) {
  const spoken = item.language === "auto" ? (item.detected_language || "auto") : item.language;
  const from = String(spoken || "en").toUpperCase();
  if (!item.translate_to) return from;
  return `${from} → ${String(item.translate_to).toUpperCase()}`;
}

function refreshLanguageAction() {
  const language = detailLanguage.value;
  const translateTo = detailTranslate.value === "off" ? "" : detailTranslate.value;
  const languageChanged = language !== savedLanguage;
  const translateChanged = translateTo !== savedTranslate;
  const pending = recordingPending;
  applyLanguages.hidden = false;
  if (pending) applyLanguages.textContent = "Transcribe";
  else if (languageChanged) applyLanguages.textContent = "Transcribe again";
  else if (translateChanged) applyLanguages.textContent = "Translate this recording";
  else applyLanguages.textContent = "Transcribe again";
}

async function applyRecordingLanguages() {
  if (!currentId) return;
  const language = detailLanguage.value;
  const translateTo = detailTranslate.value === "off" ? "" : detailTranslate.value;
  const languageChanged = language !== savedLanguage;
  const translateChanged = translateTo !== savedTranslate;
  const pending = recordingPending;
  const onlyTranslate = !pending && !languageChanged && translateChanged;
  const outcome = await ensureReady({
    language,
    translateTo: detailTranslate.value,
    model: savedModel || chosenModel(),
    persist: false,
    when: pending ? "before this audio is transcribed" : "before updating this recording",
    watch: "detail",
  });
  if (outcome === "blocked") return;
  applyLanguages.disabled = true;
  detailStatus.textContent = "";
  setFeedback({
    clientJobActive: true,
    activityActive: true,
    activityPhase: onlyTranslate ? "translate" : "transcribe",
    activityLabel: "",
    failed: false,
    failMessage: "",
  });
  startWatch("detail");
  try {
    const audioSource = transcriptAudioSelect ? transcriptAudioSelect.value : "original";
    const response = await fetch(
      onlyTranslate
        ? `/api/recordings/${currentId}/languages`
        : `/api/recordings/${currentId}/transcribe`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          onlyTranslate
            ? { language, translate_to: translateTo }
            : { language, translate_to: translateTo, audio_source: audioSource },
        ),
      },
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setFeedback({
        clientJobActive: false,
        activityActive: false,
        failed: true,
        failMessage: messageFrom(payload, "This recording was not updated"),
      });
      await ask({
        title: "This recording was not updated",
        body: messageFrom(payload, "The languages were not updated."),
        cancelLabel: "Close",
      });
      return;
    }
    applyRecordingPayload(payload);
  } catch (_error) {
    setFeedback({
      clientJobActive: false,
      activityActive: false,
      failed: true,
      failMessage: "The page lost contact with this computer.",
    });
    await ask({
      title: "This recording was not updated",
      body: "The page lost contact with this computer.",
      cancelLabel: "Close",
    });
  } finally {
    stopWatch();
    setFeedback({ clientJobActive: false });
    applyLanguages.disabled = false;
    refreshDownloads();
  }
}

async function copyTranscript() {
  const lines = turns.map((turn) => {
    const name = nameFor(turn.speaker);
    if (!turn.translation) return `${name}: ${turn.text}`;
    return `${name}: ${turn.translation}\n${name} (original): ${turn.text}`;
  });
  try {
    await navigator.clipboard.writeText(lines.join("\n\n"));
    detailStatus.textContent = "Transcript copied.";
  } catch (_error) {
    await ask({
      title: "The transcript was not copied",
      body: "The browser blocked access to the clipboard.",
      cancelLabel: "Close",
    });
  }
}

window.addEventListener("online", () => {
  refreshDownloads();
});
window.addEventListener("offline", () => {
  catalog.online = false;
  paintMarks();
  refreshRunAvailability();
});

function isOnline() {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return false;
  if (catalog && catalog.online === false) return false;
  if (catalog && catalog.online === true) return true;
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

function paintMarks() {
  const online = isOnline();
  for (const option of modelSelect.options) {
    if (option.value === "custom") {
      option.disabled = false;
      continue;
    }
    const missing = speechMissing(option.value);
    markOption(option, missing && online);
    // Offline: only installed models can be chosen. Online: missing ones stay
    // selectable so they can be downloaded once.
    option.disabled = Boolean(missing && !online);
  }
  for (const select of [languageSelect, dockLanguage, detailLanguage]) {
    for (const option of select.options) {
      const missing = spokenMissing(option.value);
      markOption(option, missing && online);
      option.disabled = Boolean(missing && !online);
    }
  }
  paintTranslationSelect(translateSelect, languageSelect.value, online);
  paintTranslationSelect(dockTranslate, dockLanguage.value, online);
  paintTranslationSelect(detailTranslate, detailLanguage.value, online);
  refreshRunAvailability();
}

function paintTranslationSelect(select, source, online) {
  for (const option of select.options) {
    const missing = translationMissing(source, option.value);
    markOption(option, missing && online);
    option.disabled = Boolean(missing && !online);
  }
}

function markOption(option, showDownloadMark) {
  const name = option.dataset.name;
  if (!name) return;
  if (option.disabled && !showDownloadMark) {
    option.textContent = `${name} (not installed)`;
    return;
  }
  option.textContent = showDownloadMark ? `${name} ↓` : name;
}

function spokenMissing(code) {
  return speechMissing(speechName(chosenModel(), code));
}

function speechName(model, language) {
  if (!model || language === "en") return model;
  return catalog.multilingual[model] || model;
}

function speechMissing(name) {
  if (!name || !Object.prototype.hasOwnProperty.call(catalog.speech || {}, name)) return false;
  return catalog.speech[name] === false;
}

function translationMissing(source, target) {
  if (!target || target === "off") return false;
  // Detect has no known spoken language yet, so the mark follows the English files.
  // Those files are also the bridge when two other languages have no direct pair.
  const from = !source || source === "auto" ? "en" : source;
  if (from === target) return false;
  return !routeReady(from, target);
}

function routeReady(source, target) {
  const pairs = new Set(catalog.pairs || []);
  if (pairs.has(`${source}:${target}`)) return true;
  if (source !== "en" && target !== "en") {
    return pairs.has(`${source}:en`) && pairs.has(`en:${target}`);
  }
  return false;
}

function refreshRunAvailability() {
  if (!downloadsLoaded) return;
  const language = (dockLanguage && dockLanguage.value) || (languageSelect && languageSelect.value) || "en";
  const translateTo = (dockTranslate && dockTranslate.value) || "off";
  const model = chosenModel();
  const gap = missingPieces(language, translateTo, model);
  const canSpeech = gap.kind === "ready" || (gap.kind === "install" && isOnline());
  if (recordButton && !recorder) {
    // Keep disabled while busy via setBusy; only gate on models when idle.
    if (!recordButton.dataset.forceBusy) {
      recordButton.disabled = !canSpeech;
    }
  }
  if (applyLanguages) {
    const detailGap = missingPieces(
      detailLanguage ? detailLanguage.value : language,
      detailTranslate ? detailTranslate.value : translateTo,
      savedModel || model,
    );
    const detailCan = detailGap.kind === "ready"
      || (detailGap.kind === "install" && isOnline());
    // Translate-only can still run when speech is ready enough for that path.
    applyLanguages.disabled = applyLanguages.dataset.forceBusy === "1" || !detailCan;
  }
}

async function refreshDownloads() {
  const response = await fetch("/api/downloads");
  if (!response.ok) return false;
  catalog = await response.json();
  downloadsLoaded = true;
  paintMarks();
  return true;
}

async function ensureReady(scope) {
  const knownReady = downloadsLoaded
    && missingPieces(scope.language, scope.translateTo, scope.model).kind === "ready";
  if (knownReady) return "ready";
  return prepareModels(scope);
}

function missingPieces(language, _translateTo, model) {
  // Recording uses one speech model. Translation and speaker files download
  // later, while the transcript is being made.
  const speech = speechName(model, language);
  if (!speech) {
    return {
      kind: "unavailable",
      body: "Choose a speech model in Settings before recording.",
    };
  }
  const speechCatalog = catalog.speech || {};
  const known = Object.prototype.hasOwnProperty.call(speechCatalog, speech);
  if (known && speechCatalog[speech] !== false) return { kind: "ready", labels: [] };
  const downloadable = (catalog.downloadable || []).includes(speech);
  if (!downloadable) {
    const body = `${speech} is not on this computer, and this app cannot download it. `
      + "Choose an installed speech model in Settings.";
    return { kind: "unavailable", body };
  }
  if (!isOnline()) {
    return {
      kind: "unavailable",
      body: `${speech} is not installed on this computer. `
        + "Connect to the internet to download it, or choose an installed model.",
    };
  }
  return { kind: "install", labels: [`Speech model ${speech}`] };
}

async function prepareModels(scope) {
  if (gateOpen) return "blocked";
  gateOpen = true;
  try {
    const fresh = await refreshDownloads();
    if (!fresh) {
      await ask({
        title: "Models could not be checked",
        body: "This page could not see which files are already on this computer.",
        cancelLabel: "Close",
      });
      return "blocked";
    }
    const gap = missingPieces(scope.language, scope.translateTo, scope.model);
    if (gap.kind === "unavailable") {
      await ask({
        title: "This model is not available",
        body: gap.body,
        cancelLabel: "Close",
      });
      return "blocked";
    }
    if (gap.kind === "install") {
      if (!isOnline()) {
        await ask({
          title: "Internet required",
          body: "Connect to the internet to download this model, or choose one that is already installed.",
          cancelLabel: "Close",
        });
        return "blocked";
      }
      const agreed = await ask({
        title: "Install the missing files?",
        body: gap.labels.length === 1
          ? `${gap.labels[0]} is not on this computer yet. Install it ${scope.when}?`
          : `These files are not on this computer yet. Install them ${scope.when}?`,
        items: gap.labels.length > 1 ? gap.labels : [],
        confirmLabel: "Install",
        cancelLabel: "Not now",
      });
      if (!agreed) return "blocked";
    }
    if (scope.persist) {
      const saved = await saveSettings({ quiet: true });
      if (!saved) return "blocked";
    }
    if (gap.kind === "ready") return "ready";
    const installed = await installFiles(scope, gap.labels);
    return installed ? "installed" : "blocked";
  } finally {
    gateOpen = false;
  }
}

async function installFiles(scope, labels) {
  setBusy(true);
  const statusEl = scope.watch === "detail" ? detailStatus : jobStatus;
  statusEl.textContent = labels.length === 1 ? `Installing ${labels[0]}…` : "Installing…";
  startWatch(scope.watch);
  try {
    const response = await fetch("/api/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language: scope.language,
        translate_to: scope.translateTo === "off" ? "" : scope.translateTo,
        model: scope.model,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      statusEl.textContent = "";
      await ask({
        title: "The download did not finish",
        body: messageFrom(payload, "Those files could not be installed."),
        cancelLabel: "Close",
      });
      return false;
    }
    catalog = payload;
    paintMarks();
    const again = missingPieces(scope.language, scope.translateTo, scope.model);
    statusEl.textContent = "";
    if (again.kind !== "ready") {
      await ask({
        title: "Still not installed",
        body: again.body || "The files are still missing. Try again in a moment.",
        cancelLabel: "Close",
      });
      return false;
    }
    return true;
  } catch (_error) {
    statusEl.textContent = "";
    await ask({
      title: "The download did not finish",
      body: "The page lost contact with this computer.",
      cancelLabel: "Close",
    });
    return false;
  } finally {
    stopWatch();
    setBusy(false);
  }
}

function ask(options) {
  dialogTitle.textContent = options.title;
  dialogBody.textContent = options.body;
  dialogList.replaceChildren();
  const items = options.items || [];
  for (const item of items) {
    const row = document.createElement("li");
    row.textContent = item;
    dialogList.appendChild(row);
  }
  dialogList.hidden = items.length === 0;
  const confirmLabel = options.confirmLabel || "";
  dialogConfirm.hidden = confirmLabel === "";
  dialogConfirm.textContent = confirmLabel;
  dialogConfirm.classList.toggle("is-danger", options.tone === "danger");
  dialogCancel.textContent = options.cancelLabel || "Cancel";
  dialogActions.classList.toggle("is-single", confirmLabel === "");
  dialog.hidden = false;
  document.body.classList.add("has-dialog");
  page.inert = true;
  dock.inert = true;
  dialogReturn = document.activeElement;
  return new Promise((resolve) => {
    dialogResolver = resolve;
    const focusTarget = confirmLabel ? dialogConfirm : dialogCancel;
    focusTarget.focus();
  });
}

function closeDialog(answer) {
  if (!dialogResolver) return;
  const resolve = dialogResolver;
  dialogResolver = null;
  dialog.hidden = true;
  document.body.classList.remove("has-dialog");
  page.inert = false;
  dock.inert = false;
  if (dialogReturn && typeof dialogReturn.focus === "function") dialogReturn.focus();
  dialogReturn = null;
  resolve(answer);
}

function onDialogKey(event) {
  if (dialog.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeDialog(false);
    return;
  }
  if (event.key !== "Tab") return;
  const buttons = [dialogCancel, dialogConfirm].filter((button) => !button.hidden);
  if (buttons.length === 0) return;
  const first = buttons[0];
  const last = buttons[buttons.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function startWatch(target) {
  window.clearInterval(watchTimer);
  const generation = ++watchGeneration;
  const tick = () => pollActivity(target, generation);
  tick();
  watchTimer = window.setInterval(tick, 400);
}

function stopWatch() {
  window.clearInterval(watchTimer);
  watchGeneration += 1;
  const keepBytes = feedbackState.saving;
  setFeedback({
    activityActive: false,
    activityPhase: "",
    activityLabel: "",
    received: keepBytes ? feedbackState.received : 0,
    total: keepBytes ? feedbackState.total : 0,
  });
}

async function pollActivity(target, generation) {
  const statusEl = target === "detail" ? detailStatus : jobStatus;
  const box = target === "detail" ? detailProgress : jobProgress;
  const track = target === "detail" ? detailTrack : jobTrack;
  const bar = target === "detail" ? detailBar : jobBar;
  const labelEl = target === "detail" ? detailProgressLabel : jobProgressLabel;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch("/api/activity", { signal: controller.signal });
    if (!response.ok || generation !== watchGeneration) return;
    const payload = await response.json();
    if (generation !== watchGeneration) return;
    paintActivity(payload, statusEl, box, track, bar, labelEl);
  } catch (_error) {
    // Keep a moving bar while the server is busy with Whisper.
    if (generation !== watchGeneration) return;
    if (feedbackState.saving) return;
    if (!feedbackState.activityActive) {
      setFeedback({
        activityActive: true,
        activityPhase: "transcribe",
        activityLabel: "",
      });
    }
  } finally {
    window.clearTimeout(timer);
  }
}

function paintActivity(payload, _statusEl, _box, _track, _bar, labelEl) {
  // Keep client upload bytes until the server reports a real phase.
  const labelText = String((labelEl && labelEl.textContent) || feedbackState.activityLabel || "");
  const clientUpload = /^(Uploading|Resuming|Reconnecting|Connection blip|Saving)/.test(labelText);
  if (clientUpload && feedbackState.saving && !payload.active) return;
  const next = {
    activityActive: Boolean(payload.active),
    activityPhase: payload.active ? String(payload.phase || "") : "",
    activityLabel: String(payload.label || ""),
  };
  // Saving and download share received/total. Leave the upload ratio in place
  // while this client is still sending the file.
  if (!feedbackState.saving) {
    next.received = Number(payload.received) || 0;
    next.total = Number(payload.total) || 0;
  }
  setFeedback(next);
}

function hideProgress(box, bar, track, options) {
  box.hidden = true;
  bar.style.width = "0%";
  bar.classList.remove("is-unknown");
  track.setAttribute("aria-valuenow", "0");
  const clearCancel = !options || options.clearCancel !== false;
  if (clearCancel && box === jobProgress) setCancelUploadVisible(false);
}

function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  if (mb >= 10) return `${Math.round(mb)} MB`;
  if (mb >= 0.1) return `${mb.toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function messageFrom(payload, fallback) {
  if (payload && typeof payload.detail === "string") return payload.detail;
  return fallback;
}

function mountMixer(root, scope) {
  if (!root) return;
  root.classList.add(scope === "dock" ? "mixer-dock" : "mixer-detail");
  root.innerHTML = `
    <div class="signal-plane-wrap">
      <canvas class="signal-plane" data-plane width="640" height="120"
        aria-label="Audio signal with filter overlay"></canvas>
      <p class="signal-plane-hint hint">
        Grey = mic in · Coral = removed by filters · Green = what gets recorded
      </p>
    </div>
    <div class="mixer-strip">
      <span class="mixer-gain-readout" data-gain-readout>1.0×</span>
      <label class="mixer-gain">
        <span class="visually-hidden">Gain</span>
        <input data-field="gain" type="range" min="0.2" max="12" step="0.1">
      </label>
      <label class="mixer-preset">
        <span class="visually-hidden">Preset</span>
        <select data-field="preset">
          <option value="off">Clean (off)</option>
          <option value="voice">Voice</option>
          <option value="speaker">Far speaker</option>
          <option value="custom">Custom</option>
        </select>
      </label>
      <label class="mixer-check"><input data-field="autoGain" type="checkbox"> Auto level</label>
      <label class="mixer-check"><input data-field="monitor" type="checkbox"> Listen</label>
      <div class="mixer-actions" data-actions></div>
    </div>
    <details class="mixer-more" data-advanced>
      <summary>Tune filters</summary>
      <div class="mixer-grid">
        <label>
          Cut rumble
          <span class="mixer-field-hint">Low thumps / table noise</span>
          <input data-field="highpass" type="range" min="0" max="200" step="5">
          <span class="mixer-field-value" data-readout="highpass">Off</span>
        </label>
        <label>
          Soften hiss
          <span class="mixer-field-hint">High air / hiss ceiling</span>
          <input data-field="lowpass" type="range" min="0" max="16000" step="250">
          <span class="mixer-field-value" data-readout="lowpass">Off</span>
        </label>
        <label>
          Hush silence
          <span class="mixer-field-hint">Mute only very quiet gaps</span>
          <input data-field="gate" type="range" min="0" max="0.08" step="0.001">
          <span class="mixer-field-value" data-readout="gate">Off</span>
        </label>
        <label>
          Tame peaks
          <span class="mixer-field-hint">Even out loud bursts</span>
          <input data-field="compression" type="range" min="0" max="1" step="0.05">
          <span class="mixer-field-value" data-readout="compression">Off</span>
        </label>
        <label>
          Kill mains hum
          <span class="mixer-field-hint">Electrical buzz</span>
          <select data-field="notch">
            <option value="off">Off</option>
            <option value="50">50 Hz (EU)</option>
            <option value="60">60 Hz (US)</option>
          </select>
        </label>
        <label>
          Auto target
          <span class="mixer-field-hint">How loud auto-level aims</span>
          <input data-field="agcTarget" type="range" min="0.08" max="0.5" step="0.01">
          <span class="mixer-field-value" data-readout="agcTarget">—</span>
        </label>
        <label>
          Auto speed
          <span class="mixer-field-hint">How fast level follows</span>
          <input data-field="agcSpeed" type="range" min="0.02" max="0.3" step="0.01">
          <span class="mixer-field-value" data-readout="agcSpeed">—</span>
        </label>
      </div>
      <button type="button" class="mixer-text-btn" data-reset-advanced>Reset to preset</button>
    </details>
  `;
  const planeCanvas = root.querySelector("[data-plane]");
  const els = {
    gainReadout: root.querySelector("[data-gain-readout]"),
    actions: root.querySelector("[data-actions]"),
    advanced: root.querySelector("[data-advanced]"),
    resetAdvanced: root.querySelector("[data-reset-advanced]"),
    monitor: root.querySelector("[data-field='monitor']"),
    plane: AudioMixer.createSignalPlane(planeCanvas),
    readouts: {
      highpass: root.querySelector('[data-readout="highpass"]'),
      lowpass: root.querySelector('[data-readout="lowpass"]'),
      gate: root.querySelector('[data-readout="gate"]'),
      compression: root.querySelector('[data-readout="compression"]'),
      agcTarget: root.querySelector('[data-readout="agcTarget"]'),
      agcSpeed: root.querySelector('[data-readout="agcSpeed"]'),
    },
    fields: {
      gain: root.querySelector("[data-field='gain']"),
      preset: root.querySelector("[data-field='preset']"),
      autoGain: root.querySelector("[data-field='autoGain']"),
      highpass: root.querySelector("[data-field='highpass']"),
      lowpass: root.querySelector("[data-field='lowpass']"),
      gate: root.querySelector("[data-field='gate']"),
      compression: root.querySelector("[data-field='compression']"),
      notch: root.querySelector("[data-field='notch']"),
      agcTarget: root.querySelector("[data-field='agcTarget']"),
      agcSpeed: root.querySelector("[data-field='agcSpeed']"),
    },
  };
  els.plane.idle();
  mixerViews.set(scope, { root, els });

  if (scope === "detail") {
    els.actions.innerHTML = `
      <button type="button" class="mixer-text-btn" data-action="save" disabled>Save cleaned</button>
      <button type="button" class="mixer-text-btn" data-action="discard" disabled>Discard</button>
    `;
    els.actions.querySelector('[data-action="save"]').addEventListener("click", saveCleanedAudio);
    els.actions.querySelector('[data-action="discard"]').addEventListener("click", discardCleanedAudio);
  } else {
    els.actions.innerHTML = `<span class="mixer-live-tag hint">Live → saved file</span>`;
  }

  els.advanced.addEventListener("toggle", () => {
    if (scope === "dock") {
      document.body.classList.toggle("is-mixer-open", els.advanced.open);
    }
  });

  els.resetAdvanced.addEventListener("click", () => {
    const preset = mixerSettings.preset === "custom" ? "off" : mixerSettings.preset;
    mixerSettings = AudioMixer.applyPreset(preset, mixerSettings);
    AudioMixer.saveSettings(mixerSettings);
    syncMixerViews();
    if (liveMixer) liveMixer.update(mixerSettings);
    scheduleDetailClean();
  });

  for (const [key, input] of Object.entries(els.fields)) {
    input.addEventListener("change", () => onMixerField(scope, key, input));
    input.addEventListener("input", () => {
      if (input.type === "range") onMixerField(scope, key, input);
    });
  }

  els.monitor.addEventListener("change", () => {
    if (liveMixer) liveMixer.setMonitor(els.monitor.checked);
  });
}

function onMixerField(scope, key, input) {
  if (key === "preset") {
    if (input.value === "custom") {
      mixerSettings.preset = "custom";
    } else {
      mixerSettings = AudioMixer.applyPreset(input.value, mixerSettings);
    }
  } else if (key === "autoGain") {
    mixerSettings.autoGain = input.checked;
    mixerSettings.preset = "custom";
  } else if (key === "notch") {
    mixerSettings.notch = input.value;
    mixerSettings.preset = "custom";
  } else {
    mixerSettings[key] = Number(input.value);
    mixerSettings.preset = "custom";
  }
  AudioMixer.saveSettings(mixerSettings);
  syncMixerViews();
  if (liveMixer) liveMixer.update(mixerSettings);
  if (scope === "detail") scheduleDetailClean();
}

function formatMixerReadout(key, value) {
  const n = Number(value) || 0;
  if (key === "highpass") return n <= 0 ? "Off" : `${Math.round(n)} Hz`;
  if (key === "lowpass") return n <= 0 ? "Off" : `${Math.round(n / 100) / 10} kHz`;
  if (key === "gate") return n <= 0 ? "Off" : n.toFixed(3);
  if (key === "compression") return n <= 0 ? "Off" : `${Math.round(n * 100)}%`;
  if (key === "agcTarget") return n.toFixed(2);
  if (key === "agcSpeed") return n.toFixed(2);
  return String(value);
}

function syncMixerViews() {
  for (const view of mixerViews.values()) {
    const { fields, gainReadout, readouts } = view.els;
    fields.gain.value = String(mixerSettings.gain);
    fields.preset.value = mixerSettings.preset;
    fields.autoGain.checked = Boolean(mixerSettings.autoGain);
    fields.highpass.value = String(mixerSettings.highpass);
    fields.lowpass.value = String(mixerSettings.lowpass || 0);
    fields.gate.value = String(mixerSettings.gate);
    fields.compression.value = String(mixerSettings.compression);
    fields.notch.value = mixerSettings.notch;
    fields.agcTarget.value = String(mixerSettings.agcTarget);
    fields.agcSpeed.value = String(mixerSettings.agcSpeed);
    gainReadout.textContent = `${Number(mixerSettings.gain).toFixed(1)}×`;
    if (readouts) {
      for (const key of Object.keys(readouts)) {
        if (readouts[key]) readouts[key].textContent = formatMixerReadout(key, mixerSettings[key]);
      }
    }
  }
}

function paintMixerLevel(scope, level, gainValue) {
  const view = mixerViews.get(scope);
  if (!view) return;
  view.els.gainReadout.textContent = `${Number(gainValue || mixerSettings.gain).toFixed(1)}×`;
}

function paintSignalPlane(scope, frame) {
  const view = mixerViews.get(scope);
  if (!view || !view.els.plane) return;
  view.els.plane.draw(frame);
}

let detailCleanTimer = 0;
function scheduleDetailClean() {
  if (!currentId || !document.body.classList.contains("is-detail")) return;
  window.clearTimeout(detailCleanTimer);
  detailCleanTimer = window.setTimeout(() => {
    previewCleanedAudio({ quiet: true });
  }, 350);
}


function updateDetailMixerActions() {
  const view = mixerViews.get("detail");
  if (!view) return;
  const saveButton = view.els.actions.querySelector('[data-action="save"]');
  const discardButton = view.els.actions.querySelector('[data-action="discard"]');
  if (saveButton) saveButton.disabled = !previewBlob;
  if (discardButton) discardButton.disabled = !hasCleaned && !previewBlob;
}

let detailPlaneToken = 0;

async function decodeOriginalAudio() {
  if (!originalAudioUrl) return null;
  const response = await fetch(originalAudioUrl);
  if (!response.ok) throw new Error("fetch failed");
  const raw = await response.arrayBuffer();
  const context = new AudioContext();
  try {
    return await context.decodeAudioData(raw.slice(0));
  } finally {
    await context.close().catch(() => {});
  }
}

async function paintDetailOriginalPlane() {
  if (!currentId || !originalAudioUrl) return;
  const token = ++detailPlaneToken;
  try {
    const decoded = await decodeOriginalAudio();
    if (!decoded || token !== detailPlaneToken || currentId == null) return;
    // Same buffer for both until filter preview finishes — still shows grey+green.
    paintOfflinePlane(decoded, decoded);
  } catch (_error) {
    // Keep the empty plane; filter preview may still succeed.
  }
}

async function previewCleanedAudio(options = {}) {
  if (!currentId || !originalAudioUrl) return;
  const quiet = Boolean(options.quiet);
  const token = ++detailPlaneToken;
  if (!quiet) detailStatus.textContent = "Cleaning audio…";
  try {
    const decoded = await decodeOriginalAudio();
    if (!decoded || token !== detailPlaneToken) return;
    paintOfflinePlane(decoded, decoded);
    const rendered = await AudioMixer.processBuffer(decoded, mixerSettings);
    if (token !== detailPlaneToken || currentId == null) return;
    clearPreview();
    previewBlob = AudioMixer.bufferToWavBlob(rendered);
    previewUrl = URL.createObjectURL(previewBlob);
    if (listenAudioSelect) {
      const previewOpt = listenAudioSelect.querySelector('option[value="preview"]');
      if (previewOpt) previewOpt.disabled = false;
      listenAudioSelect.value = "preview";
    }
    refreshPlayerSource();
    updateDetailMixerActions();
    paintOfflinePlane(decoded, rendered);
    detailStatus.textContent = quiet
      ? "Filters applied — Save cleaned to keep."
      : "Filters applied — Save cleaned to keep.";
  } catch (_error) {
    if (quiet) {
      detailStatus.textContent = "Could not apply filters to this file.";
      return;
    }
    detailStatus.textContent = "";
    await ask({
      title: "Could not clean this audio",
      body: "The browser could not decode or process that file.",
      cancelLabel: "Close",
    });
  }
}

function paintOfflinePlane(rawBuffer, processedBuffer) {
  const view = mixerViews.get("detail");
  if (!view || !view.els.plane) return;
  const raw = rawBuffer.getChannelData(0);
  const processed = processedBuffer.numberOfChannels
    ? processedBuffer.getChannelData(0)
    : raw;
  const points = 640;
  const rawOut = AudioMixer.peakEnvelope(raw, points);
  const procOut = AudioMixer.peakEnvelope(processed, points);
  let rawSum = 0;
  let procSum = 0;
  for (let i = 0; i < points; i += 1) {
    rawSum += rawOut[i] * rawOut[i];
    procSum += procOut[i] * procOut[i];
  }
  view.els.plane.draw({
    raw: rawOut,
    processed: procOut,
    rawRms: Math.sqrt(rawSum / points),
    processedRms: Math.sqrt(procSum / points),
    gain: mixerSettings.gain,
    gate: 1,
  });
  // Detail was often hidden when the canvas first sized; redraw after layout.
  requestAnimationFrame(() => view.els.plane.redraw());
}

async function saveCleanedAudio() {
  if (!currentId || !previewBlob) return;
  detailStatus.textContent = "Saving cleaned audio…";
  const body = new FormData();
  body.append("audio", previewBlob, "audio_cleaned.wav");
  try {
    const response = await fetch(`/api/recordings/${currentId}/cleaned`, {
      method: "PUT",
      body,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      detailStatus.textContent = "";
      await ask({
        title: "Cleaned audio was not saved",
        body: messageFrom(payload, "Try applying the preview again."),
        cancelLabel: "Close",
      });
      return;
    }
    clearPreview();
    applyRecordingPayload(payload);
    detailStatus.textContent = "Cleaned audio saved.";
  } catch (_error) {
    detailStatus.textContent = "";
    await ask({
      title: "Cleaned audio was not saved",
      body: "The page lost contact with this computer.",
      cancelLabel: "Close",
    });
  }
}

async function discardCleanedAudio() {
  if (!currentId) return;
  if (previewBlob) {
    clearPreview();
    if (listenAudioSelect) {
      const previewOpt = listenAudioSelect.querySelector('option[value="preview"]');
      if (previewOpt) previewOpt.disabled = true;
      listenAudioSelect.value = hasCleaned ? "cleaned" : "original";
    }
    refreshPlayerSource();
    updateDetailMixerActions();
    detailStatus.textContent = "Preview discarded.";
    return;
  }
  if (!hasCleaned) return;
  const agreed = await ask({
    title: "Remove cleaned audio?",
    body: "The original recording stays. Only the saved cleaned file is removed.",
    confirmLabel: "Remove",
    cancelLabel: "Keep it",
    tone: "danger",
  });
  if (!agreed) return;
  const response = await fetch(`/api/recordings/${currentId}/cleaned`, { method: "DELETE" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    await ask({
      title: "Cleaned audio was not removed",
      body: messageFrom(payload, "Try again in a moment."),
      cancelLabel: "Close",
    });
    return;
  }
  applyRecordingPayload(payload);
  detailStatus.textContent = "Cleaned audio removed.";
}
