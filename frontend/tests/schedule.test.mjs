import assert from "node:assert/strict";
import test from "node:test";
import { clockChangeIssue, defaultDraft, draftFromDetail, formatDuration, localDate, payloadForSave, sandboxShortWindow, scheduleSummary } from "../src/host/model.ts";

const ZONES = ["Europe/London", "America/New_York", "Asia/Kolkata", "Pacific/Chatham", "UTC"];
const INSTANTS = [
  "2026-11-07T18:34:39.598Z", // ordinary GMT afternoon
  "2026-03-29T00:52:00.250Z", // window spans the London GMT->BST change at 01:00Z
  "2026-10-25T00:50:00.001Z", // window spans the London BST->GMT change at 01:00Z
  "2026-12-31T23:50:00.000Z", // crosses a London calendar day and year
];

function withZone(zone, run) {
  const previous = process.env.TZ;
  process.env.TZ = zone;
  try { return run(); } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous; }
}

function detailFor(schedule) {
  return { title: "t", description: "", financials: { ...defaultDraft().financials, materials: [] },
    opens_at: schedule.opens_at, closes_at: schedule.closes_at };
}

// The repeated London hour (BST->GMT): wall times there name two instants.
const FALLBACK = "2026-10-25T00:50:00.001Z";
const unambiguous = (zone, iso) => !(zone === "Europe/London" && iso === FALLBACK);

test("preset uses the click instant: opens 1 minute before, cutoff 15 minutes after", () => {
  for (const zone of ZONES) withZone(zone, () => {
    for (const iso of INSTANTS.filter((value) => unambiguous(zone, value))) {
      const clicked = new Date(iso);
      const saved = payloadForSave({ ...defaultDraft(), schedule: sandboxShortWindow(clicked) }).schedule;
      assert.equal(saved.opens_at, new Date(clicked.getTime() - 60_000).toISOString(), `${zone} ${iso}`);
      assert.equal(saved.closes_at, new Date(clicked.getTime() + 15 * 60_000).toISOString(), `${zone} ${iso}`);
    }
  });
  // Two clicks far apart yield different windows: nothing is captured at module load.
  const a = sandboxShortWindow(new Date("2026-11-07T10:00:00Z")), b = sandboxShortWindow(new Date("2026-11-07T18:00:00Z"));
  assert.notEqual(a.closes_at, b.closes_at);
  assert.throws(() => sandboxShortWindow(new Date("invalid")));
});

test("dates survive editor value -> save request -> persisted detail -> editor/review in every zone", () => {
  for (const zone of ZONES) withZone(zone, () => {
    for (const iso of INSTANTS.filter((value) => unambiguous(zone, value))) {
      const editor = sandboxShortWindow(new Date(iso));
      assert.equal(clockChangeIssue(editor.opens_at), null);
      assert.equal(clockChangeIssue(editor.closes_at), null);
      assert.match(editor.opens_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$/, "datetime-local value with step=0.001");
      const request = payloadForSave({ ...defaultDraft(), schedule: editor }).schedule;
      // Backend persists the instant; responses may use a different but equivalent ISO spelling.
      const persisted = { opens_at: request.opens_at.replace("Z", "+00:00"), closes_at: request.closes_at.replace("Z", "+00:00") };
      const reloaded = draftFromDetail(detailFor(persisted)).schedule;
      assert.deepEqual(reloaded, editor, `${zone} ${iso}: reloaded editor values`);
      assert.deepEqual(payloadForSave({ ...defaultDraft(), schedule: reloaded }).schedule, request, `${zone} ${iso}: resave is stable`);
      const summary = scheduleSummary(reloaded, new Date(iso));
      assert.equal(summary.duration, "16 min");
      assert.equal(summary.remaining, "15 min until cutoff");
    }
    assert.equal(localDate("2026-11-07T18:34:39.598Z").length, 23);
  });
});

test("summary states today/tomorrow, exact London timestamp, duration and remaining time", () => {
  const now = new Date("2026-11-07T18:34:39.598Z");
  const preset = scheduleSummary(sandboxShortWindow(now), now);
  assert.equal(preset.opensPhrase, "Opened today at 18:33:39 GMT");
  assert.equal(preset.closesPhrase, "Closes today at 18:49:39 GMT");
  assert.match(preset.closes, /7 Nov 2026, 18:49:39 GMT/);
  assert.equal(preset.duration, "16 min");
  assert.equal(preset.remaining, "15 min until cutoff");

  // The two observed test campaigns: an untouched default cutoff 25 hours after page load.
  const accidental = scheduleSummary({ opens_at: "2026-11-07T18:36:39.598Z", closes_at: "2026-11-08T19:34:39.598Z" }, now);
  assert.equal(accidental.closesPhrase, "Closes tomorrow at 19:34:39 GMT");
  assert.equal(accidental.duration, "1 day 58 min");
  assert.equal(accidental.remaining, "1 day 1 h until cutoff");

  const summer = scheduleSummary({ opens_at: "2026-07-01T09:00:00Z", closes_at: "2026-07-03T09:00:00Z" }, new Date("2026-07-01T09:30:00Z"));
  assert.equal(summer.closesPhrase, "Closes on Fri, 3 Jul 2026 at 10:00:00 BST");
  const past = scheduleSummary(sandboxShortWindow(now), new Date(now.getTime() + 16 * 60_000));
  assert.equal(past.remaining, "Cutoff has passed");
  assert.match(past.closesPhrase, /^Closed today at/);
  assert.equal(scheduleSummary({ opens_at: "", closes_at: "2026-11-08T00:00:00Z" }, now), null);
  assert.equal(scheduleSummary({ opens_at: "2026-11-08T00:00:00Z", closes_at: "2026-11-07T00:00:00Z" }, now).duration,
    "Invalid: cutoff is not after opening");
  assert.equal(formatDuration(45_000), "45 s");
});

test("ordinary default campaign policy is unchanged", () => {
  const draft = defaultDraft();
  const saved = payloadForSave(draft).schedule;
  const opens = Date.parse(saved.opens_at), closes = Date.parse(saved.closes_at);
  assert.ok(Math.abs(opens - Date.now() - 3_600_000) < 5_000);
  assert.equal(closes - opens, 24 * 3_600_000);
});

test("repeated or skipped clock-change wall times are detected instead of silently shifted", () => {
  withZone("Europe/London", () => {
    const window = sandboxShortWindow(new Date(FALLBACK)); // cutoff 01:05 local exists twice on 25 Oct
    assert.equal(clockChangeIssue(window.closes_at), "ambiguous");
    assert.equal(clockChangeIssue("2026-10-25T01:30"), "ambiguous");
    assert.equal(clockChangeIssue("2026-03-29T01:30:00.000"), "nonexistent"); // skipped by GMT->BST
    assert.equal(clockChangeIssue("2026-03-29T02:30:00.000"), null);
    assert.equal(clockChangeIssue("2026-11-07T18:49:39.598"), null);
    assert.equal(clockChangeIssue("2026-11-07T18:49"), null);
    assert.equal(clockChangeIssue(""), null);
  });
  withZone("UTC", () => assert.equal(clockChangeIssue("2026-10-25T01:30:00.000"), null));
});
