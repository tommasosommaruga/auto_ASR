import test from "node:test";
import assert from "node:assert/strict";
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
  assert.equal(out.progress.mode, "indeterminate");
  assert.match(out.label, /saving audio/i);
});

test("saving with a known size is determinate", () => {
  const out = resolve({ ...base(), saving: true, received: 25, total: 100 });
  assert.equal(out.flow, "saving");
  assert.equal(out.progress.mode, "determinate");
  assert.equal(out.progress.ratio, 0.25);
  assert.match(out.label, /25%/);
});

test("saving beats activity and uses upload bytes", () => {
  const out = resolve({
    ...base(),
    saving: true,
    received: 40,
    total: 80,
    activityActive: true,
    activityPhase: "download",
    activityLabel: "Speech model",
  });
  assert.equal(out.flow, "saving");
  assert.equal(out.progress.mode, "determinate");
  assert.equal(out.progress.ratio, 0.5);
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

test("activity transcribe with totals is determinate", () => {
  const out = resolve({
    ...base(),
    activityActive: true,
    activityPhase: "transcribe",
    activityLabel: "Transcribing · 8% · 581k frames left",
    received: 50000,
    total: 643406,
  });
  assert.equal(out.flow, "working");
  assert.equal(out.progress.mode, "determinate");
  assert.ok(out.progress.ratio > 0.07 && out.progress.ratio < 0.09);
  assert.match(out.label, /8%/);
  assert.match(out.label, /frames left/i);
});

test("chunk transcription shows count under the bar", () => {
  const out = resolve({
    ...base(),
    activityActive: true,
    activityPhase: "transcribe",
    activityLabel: "Transcribing 16/72 · 22% · ~8m left",
    received: 16,
    total: 72,
  });
  assert.equal(out.flow, "working");
  assert.equal(out.progress.mode, "determinate");
  assert.ok(Math.abs(out.progress.ratio - 16 / 72) < 0.001);
  assert.match(out.label, /16\/72/);
  assert.match(out.label, /8m left/);
  assert.match(out.progress.text, /chunks/i);
  assert.match(out.progress.text, /22%/);
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

test("client job holds working after activity clears", () => {
  const out = resolve({
    ...base(),
    clientJobActive: true,
    activityActive: false,
    activityPhase: "transcribe",
    itemPending: true,
  });
  assert.equal(out.flow, "working");
  assert.match(out.label, /transcrib/i);
});

test("empty transcript stays pending item", () => {
  const out = resolve({
    ...base(),
    itemPending: false,
    hasTranscript: false,
  });
  assert.equal(out.item, "pending");
  assert.match(out.label, /no speech/i);
});
