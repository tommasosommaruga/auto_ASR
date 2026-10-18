/* Pure stage resolution for dock strip + item badges. No DOM. */
(function (root) {
  function resolve(input) {
    const i = input || {};
    const recording = Boolean(i.recording);
    const saving = Boolean(i.saving);
    const failed = Boolean(i.failed);
    const activityActive = Boolean(i.activityActive);
    // Client holds Working until the fetch settles, even if /api/activity cleared.
    const clientJobActive = Boolean(i.clientJobActive);
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
      if (total > 0) {
        const ratio = Math.max(0, Math.min(1, received / total));
        const percent = Math.round(ratio * 100);
        label = `Saving · ${percent}%`;
        progress = { mode: "determinate", ratio, text: label };
      } else {
        label = "Saving audio…";
        progress = { mode: "indeterminate", ratio: 0, text: label };
      }
    } else if (activityActive || clientJobActive) {
      flow = "working";
      if (phase === "download" && activityActive) {
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
      } else if (total > 0) {
        const ratio = Math.max(0, Math.min(1, received / total));
        const percent = Math.round(ratio * 100);
        label = activityLabel
          ? (activityLabel.startsWith("Working") ? activityLabel : `Working · ${activityLabel}`)
          : `Working · Transcribing · ${percent}%`;
        progress = { mode: "determinate", ratio, text: label };
      } else {
        label = activityLabel
          ? (activityLabel.startsWith("Working") ? activityLabel : `Working · ${activityLabel}`)
          : "Working · Transcribing…";
        progress = { mode: "indeterminate", ratio: 0, text: label };
      }
    }

    let item = "none";
    // Failed only overrides the label when flow is quiet; strip still follows flow.
    if (failed && flow === "idle") {
      item = "failed";
      label = failMessage || "Something went wrong — audio kept if already saved";
    } else if (failed) {
      item = "failed";
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
