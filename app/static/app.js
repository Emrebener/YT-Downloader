"use strict";

const AUDIO_FORMATS = ["mp3", "m4a", "opus", "flac", "wav"];
const VIDEO_FORMATS = ["mp4", "webm", "mkv"];
const AUDIO_QUALITY = [["320", "320 kbps"], ["256", "256 kbps"],
                       ["192", "192 kbps"], ["128", "128 kbps"]];
const VIDEO_QUALITY = [["best", "Best"], ["2160", "2160p"], ["1440", "1440p"],
                       ["1080", "1080p"], ["720", "720p"], ["480", "480p"],
                       ["360", "360p"]];
const LOSSLESS = ["flac", "wav"];

let mode = "audio";

const $ = (id) => document.getElementById(id);

function fillSelect(sel, pairs) {
  sel.replaceChildren();
  for (const [value, label] of pairs) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    sel.appendChild(opt);
  }
}

function refreshOptions() {
  if (mode === "audio") {
    fillSelect($("format"), AUDIO_FORMATS.map((f) => [f, f.toUpperCase()]));
    fillSelect($("quality"), AUDIO_QUALITY);
  } else {
    fillSelect($("format"), VIDEO_FORMATS.map((f) => [f, f.toUpperCase()]));
    fillSelect($("quality"), VIDEO_QUALITY);
  }
  syncQualityState();
}

function syncQualityState() {
  $("quality").disabled = mode === "audio" && LOSSLESS.includes($("format").value);
}

function currentOptions() {
  return {
    mode: mode,
    format: $("format").value,
    quality: $("quality").value,
    thumbnail: $("thumbnail").checked,
    metadata: $("metadata").checked,
  };
}

function fmtDuration(secs) {
  if (secs == null) return "";
  secs = Math.round(secs);
  const m = Math.floor(secs / 60);
  const s = String(secs % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = false;
}
function clearError() { $("error").hidden = true; }
function setStatus(msg) {
  $("status").textContent = msg || "";
  $("status").hidden = !msg;
}

async function inspectUrl(url) {
  const res = await fetch("/api/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || "Could not read that URL.");
  }
  return res.json();
}

// Two-step handshake: POST /api/download -> {token}, then navigate to the file.
async function downloadOne(url, options) {
  const res = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ url: url }, options)),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || "Download failed.");
  }
  const { token } = await res.json();
  const sink = $("sink");
  sink.href = "/api/file/" + token;
  sink.click();
}

function downloadZip(options) {
  const params = new URLSearchParams({
    url: $("url").value.trim(),
    mode: options.mode,
    format: options.format,
    quality: options.quality,
    thumbnail: String(options.thumbnail),
    metadata: String(options.metadata),
  });
  const sink = $("sink");
  sink.href = "/api/download-zip?" + params.toString();
  sink.click();
}

function setTrackStatus(row, state, message) {
  const el = row.querySelector(".track-status");
  const btn = row.querySelector("button");
  el.className = "track-status " + (state || "");
  if (state === "downloading") { el.textContent = "downloading…"; btn.disabled = true; }
  else if (state === "done") { el.textContent = "done"; btn.disabled = false; }
  else if (state === "error") { el.textContent = message || "failed"; btn.disabled = false; }
  else { el.textContent = ""; btn.disabled = false; }
}

function buildTrackRow(entry, index, options) {
  const row = document.createElement("div");
  row.className = "track";

  const thumb = document.createElement(entry.thumbnail ? "img" : "div");
  thumb.className = "thumb";
  if (entry.thumbnail) thumb.src = entry.thumbnail;

  const meta = document.createElement("div");
  meta.className = "meta";
  const label = `${index + 1}. ${entry.channel} — ${entry.title} `;
  meta.appendChild(document.createTextNode(label));
  const dur = document.createElement("span");
  dur.className = "dur";
  dur.textContent = fmtDuration(entry.duration);
  meta.appendChild(dur);

  const status = document.createElement("span");
  status.className = "track-status";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "Download";
  btn.addEventListener("click", async () => {
    setTrackStatus(row, "downloading");
    try {
      await downloadOne(entry.url, options);
      setTrackStatus(row, "done");
    } catch (e) {
      setTrackStatus(row, "error", e.message);
    }
  });

  row.append(thumb, meta, status, btn);
  return row;
}

function renderPlaylist(info) {
  const options = currentOptions();
  const results = $("results");
  results.replaceChildren();

  const head = document.createElement("div");
  head.className = "pl-head";

  const title = document.createElement("div");
  title.className = "pl-title";
  title.textContent = `${info.title} · ${info.count} videos`;

  const actions = document.createElement("div");
  actions.className = "pl-actions";

  const zipBtn = document.createElement("button");
  zipBtn.type = "button";
  zipBtn.textContent = "Download all (ZIP)";
  zipBtn.addEventListener("click", () => downloadZip(options));

  const seqBtn = document.createElement("button");
  seqBtn.type = "button";
  seqBtn.className = "secondary";
  seqBtn.textContent = "Download all (one by one)";

  actions.append(zipBtn, seqBtn);
  head.append(title, actions);
  results.appendChild(head);

  const rows = info.entries.map((entry, i) => {
    const row = buildTrackRow(entry, i, options);
    results.appendChild(row);
    return row;
  });

  seqBtn.addEventListener("click", async () => {
    zipBtn.disabled = true;
    seqBtn.disabled = true;
    for (let i = 0; i < info.entries.length; i++) {
      setTrackStatus(rows[i], "downloading");
      try {
        await downloadOne(info.entries[i].url, options);
        setTrackStatus(rows[i], "done");
      } catch (e) {
        setTrackStatus(rows[i], "error", e.message);
      }
    }
    zipBtn.disabled = false;
    seqBtn.disabled = false;
  });
}

async function onDownload() {
  const url = $("url").value.trim();
  clearError();
  $("results").replaceChildren();
  if (!url) { showError("Paste a URL first."); return; }

  $("download-btn").disabled = true;
  setStatus("Reading URL…");
  try {
    const info = await inspectUrl(url);
    if (info.type === "video") {
      setStatus("Downloading…");
      await downloadOne(url, currentOptions());
      setStatus("");
    } else {
      setStatus("");
      renderPlaylist(info);
    }
  } catch (e) {
    setStatus("");
    showError(e.message);
  } finally {
    $("download-btn").disabled = false;
  }
}

function init() {
  refreshOptions();

  $("mode-toggle").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-mode]");
    if (!btn) return;
    mode = btn.dataset.mode;
    for (const b of $("mode-toggle").children) {
      b.classList.toggle("active", b === btn);
    }
    refreshOptions();
  });

  $("format").addEventListener("change", syncQualityState);
  $("download-btn").addEventListener("click", onDownload);
  $("url").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") onDownload();
  });
}

init();
