(() => {
  "use strict";

  const state = {
    path: null,
    breadcrumbs: [],
    folders: [],
    files: [],
    selectedKind: null,   // 'folder' | 'file'
    selectedIndex: -1,    // index within combined [folders..., files...] display list
    selectedFile: null,   // the file entry object currently shown in detail pane
    sets: [],
    activeSetId: 1,
    setMembers: [],
    setSelectedIndex: -1,
    pane: "browser",      // 'browser' | 'set' | 'detail'
    autoplay: true,
    waveformPeaks: null,
    waveformDuration: 0,
    selectedSampleId: null,

    editor: {
      open: false,
      clipId: null,
      sampleId: null,
      name: "",
      path: null,
      duration: 0,
      peaks: null,
      viewStart: 0,
      viewEnd: 0,
      clipStart: 0,
      clipEnd: 0,
      fadeInWidth: 0, fadeInCpX: 0.5, fadeInCpY: 0.5,
      fadeOutWidth: 0, fadeOutCpX: 0.5, fadeOutCpY: 0.5,
      drag: null,       // {mode, startX, orig...}
      playing: false,
      loop: true,
    },
  };

  const $ = (sel) => document.querySelector(sel);
  const audioEl = $("#audioEl");

  // ---------------------------------------------------------- formatting

  function fmtDuration(seconds) {
    if (seconds == null) return "--";
    return seconds.toFixed(2) + "s";
  }
  function fmtSize(bytes) {
    if (bytes == null) return "--";
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return mb.toFixed(1) + "MB";
    return (bytes / 1024).toFixed(1) + "KB";
  }
  function fmtTime(seconds) {
    if (!isFinite(seconds)) seconds = 0;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  // ---------------------------------------------------------- API helpers

  async function getJSON(url) {
    const res = await fetch(url);
    return res.json();
  }
  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return res.json();
  }

  // ---------------------------------------------------------- browsing

  async function browse(path) {
    const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : "/api/browse";
    const data = await getJSON(url);
    if (data.error) return;
    state.path = data.path;
    state.breadcrumbs = data.breadcrumbs;
    state.folders = data.folders;
    state.files = data.files;
    state.selectedIndex = state.folders.length > 0 || state.files.length > 0 ? 0 : -1;
    renderBreadcrumbs();
    renderFileList();
    if (state.files.length && state.selectedIndex >= state.folders.length) {
      selectFileByDisplayIndex(state.selectedIndex);
    }
  }

  function renderBreadcrumbs() {
    $("#breadcrumbPath").textContent =
      "Collections" + (state.breadcrumbs.length ? " / " + state.breadcrumbs.map(b => b.name || "/").join(" / ") : "");
    $("#itemCount").textContent = `${state.folders.length + state.files.length} items`;
  }

  function combinedList() {
    return [
      ...state.folders.map(f => ({ ...f, _kind: "folder" })),
      ...state.files.map(f => ({ ...f, _kind: "file" })),
    ];
  }

  function renderFileList() {
    const list = combinedList();
    const container = $("#fileList");
    container.innerHTML = "";
    list.forEach((entry, i) => {
      const row = document.createElement("div");
      row.className = "row" + (i === state.selectedIndex ? " selected" : "");
      row.dataset.index = i;

      if (entry._kind === "folder") {
        row.innerHTML = `
          <span class="row-icon">
            <svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2H3V6zm0 4h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8z"/></svg>
          </span>
          <span class="row-name folder-name">${escapeHtml(entry.name)}</span>
          <span class="row-meta">--</span>
          <span class="row-meta size">folder</span>`;
        row.addEventListener("dblclick", () => browse(entry.path));
      } else {
        const checked = entry.in_active_set;
        row.innerHTML = `
          <span class="row-icon">
            ${checked ? '<span class="row-check">&#10003;</span>' :
              '<svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>'}
          </span>
          <span class="row-name">${escapeHtml(entry.name)}</span>
          <span class="row-meta">${fmtDuration(entry.duration)}</span>
          <span class="row-meta size">${fmtSize(entry.size)}</span>`;
        row.addEventListener("dblclick", () => toggleActiveSetMember(entry.path));
      }
      row.addEventListener("click", () => {
        state.selectedIndex = i;
        state.pane = "browser";
        renderFileList();
        if (entry._kind === "file") selectFile(entry);
      });
      container.appendChild(row);
    });
  }

  function selectFileByDisplayIndex(i) {
    const list = combinedList();
    const entry = list[i];
    if (entry && entry._kind === "file") selectFile(entry);
  }

  async function selectFile(entry, opts = {}) {
    state.selectedFile = entry;
    $("#nowPlaying").textContent = entry.name;
    if (!opts.keepEditor) closeEditor();
    await loadDetail(entry.path);
    loadAudioSource(entry.path);
    if (state.autoplay && !opts.keepEditor) playAudio();
  }

  // ---------------------------------------------------------- detail pane

  async function loadDetail(path) {
    const [detail, waveform] = await Promise.all([
      getJSON(`/api/sample?path=${encodeURIComponent(path)}`),
      getJSON(`/api/sample/waveform?path=${encodeURIComponent(path)}`),
    ]);
    if (detail.error) return;

    state.selectedSampleId = detail.id;

    $("#detailEmpty").style.display = "none";
    $("#detailContent").style.display = "flex";

    $("#detailName").textContent = detail.name;
    $("#detailPath").textContent = detail.path;

    const bpm = detail.bpm != null ? detail.bpm.toFixed ? detail.bpm.toFixed(0) : detail.bpm : "—";
    // An explicit tag/filename value is ground truth, not a probabilistic
    // estimate — show full confidence rather than a misleading 0.00.
    const bpmFromTag = detail.bpm_tag != null || detail.bpm_filename != null;
    const bpmConfRaw = detail.bpm_confidence ?? detail.grid_stability ?? (bpmFromTag ? 1 : 0);
    const bpmConf = bpmConfRaw.toFixed(2);
    const key = detail.key_name || "—";
    const keyFromTag = detail.key_tag != null && detail.key_tag === detail.key_name;
    const keyConf = (detail.key_confidence ?? (keyFromTag ? 1 : 0)).toFixed(2);
    const pitch = detail.pitch_note || "—";
    const pitchConf = (detail.pitch_confidence ?? 0).toFixed(2);
    $("#analysisLine").innerHTML =
      `BPM: <b>${bpm}</b> (${bpmConf})&nbsp;&nbsp;&nbsp;Key: <b>${key}</b> (${keyConf})&nbsp;&nbsp;&nbsp;Pitch: <b>${pitch}</b> (${pitchConf})`;

    const fmt = (detail.format || "").toUpperCase();
    const chanLabel = detail.channels === 1 ? "Mono" : detail.channels === 2 ? "Stereo" : `${detail.channels}ch`;
    $("#formatLine").innerHTML =
      `<b>${fmt}</b> &middot; <b>${chanLabel}</b> &middot; <b>${(detail.sample_rate / 1000).toFixed(1)}kHz</b> &middot; <b>${detail.bit_depth}bit</b> &middot; <b>${fmtSize(detail.size)}</b> &middot; <b>${fmtTime(detail.duration)}</b>`;
    $("#miniFormat").textContent = `${(detail.sample_rate / 1000).toFixed(1)}kHz`;

    $("#inSetsPills").innerHTML = (detail.sets || [])
      .map(s => `<span class="pill-tag in-set">${escapeHtml(s)}</span>`).join("") || `<span class="pill-tag in-set" style="opacity:.4">none</span>`;

    $("#notesBox").value = detail.notes || "";
    $("#notesBox").dataset.path = detail.path;

    renderTagPills(detail.tags || [], detail.path);

    state.waveformPeaks = waveform.peaks || [];
    state.waveformDuration = waveform.duration || detail.duration || 0;
    drawWaveform(0);
  }

  function renderTagPills(tags, path) {
    const container = $("#tagPills");
    container.innerHTML = "";
    tags.forEach(tag => {
      const pill = document.createElement("span");
      pill.className = "pill-tag";
      pill.textContent = tag;
      pill.title = "Click to remove";
      pill.addEventListener("click", async () => {
        await postJSON("/api/sample/tag", { path, tag, remove: true });
        loadDetail(path);
      });
      container.appendChild(pill);
    });
    const addBtn = document.createElement("span");
    addBtn.className = "pill-add";
    addBtn.textContent = "+";
    addBtn.title = "Add tag";
    addBtn.addEventListener("click", async () => {
      const tag = prompt("Tag name:");
      if (tag && tag.trim()) {
        await postJSON("/api/sample/tag", { path, tag: tag.trim() });
        loadDetail(path);
      }
    });
    container.appendChild(addBtn);
  }

  $("#notesBox").addEventListener("change", (e) => {
    postJSON("/api/sample/notes", { path: e.target.dataset.path, notes: e.target.value });
  });

  // ---------------------------------------------------------- waveform canvas

  function drawWaveform(progressFraction) {
    const canvas = $("#waveformCanvas");
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 560;
    const height = canvas.clientHeight || 110;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const peaks = state.waveformPeaks;
    if (!peaks || !peaks.length) return;

    const mid = height / 2;
    const n = peaks.length;
    const barWidth = width / n;
    const playX = width * progressFraction;

    function colorAt(frac, dim) {
      // purple -> magenta -> orange -> gold, matching the real app's gradient
      const stops = [
        [139, 92, 246], [233, 79, 214], [251, 146, 60], [251, 191, 36],
      ];
      const pos = Math.min(0.999, Math.max(0, frac)) * (stops.length - 1);
      const i = Math.floor(pos);
      const t = pos - i;
      const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
      const r = a[0] + (b[0] - a[0]) * t;
      const g = a[1] + (b[1] - a[1]) * t;
      const bl = a[2] + (b[2] - a[2]) * t;
      const alpha = dim ? 0.35 : 0.95;
      return `rgba(${r | 0},${g | 0},${bl | 0},${alpha})`;
    }

    for (let i = 0; i < n; i++) {
      const [mn, mx] = peaks[i];
      const x = i * barWidth;
      const yMax = mid - mx * mid * 0.92;
      const yMin = mid - mn * mid * 0.92;
      const dim = x > playX;
      ctx.fillStyle = colorAt(i / n, dim);
      ctx.fillRect(x, yMax, Math.max(1, barWidth - 0.4), Math.max(1, yMin - yMax));
    }

    // center line
    ctx.strokeStyle = "rgba(255,255,255,0.15)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(width, mid);
    ctx.stroke();

    // playhead
    if (progressFraction > 0) {
      ctx.strokeStyle = "rgba(255,255,255,0.9)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(playX, 0);
      ctx.lineTo(playX, height);
      ctx.stroke();
    }
  }

  $("#waveformCanvas").addEventListener("click", (e) => {
    const rect = e.target.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    if (audioEl.duration) {
      audioEl.currentTime = frac * audioEl.duration;
    }
  });
  $("#waveformCanvas").addEventListener("dblclick", () => openEditor());
  $("#waveViewBtn").addEventListener("click", () => openEditor());

  // ---------------------------------------------------------- playback

  function loadAudioSource(path) {
    audioEl.src = `/api/audio?path=${encodeURIComponent(path)}`;
  }
  function playAudio() {
    audioEl.play().catch(() => {});
  }
  function togglePlay() {
    if (!audioEl.src) return;
    if (audioEl.paused) playAudio(); else audioEl.pause();
  }
  audioEl.addEventListener("play", () => {
    $("#playIcon").innerHTML = '<path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z"/>';
  });
  audioEl.addEventListener("pause", () => {
    $("#playIcon").innerHTML = '<path fill="currentColor" d="M8 5v14l11-7z"/>';
  });
  audioEl.addEventListener("timeupdate", () => {
    const dur = audioEl.duration || state.waveformDuration || 0;
    const frac = dur ? audioEl.currentTime / dur : 0;
    $("#seekFill").style.width = `${frac * 100}%`;
    $("#timeLabel").textContent = fmtTime(audioEl.currentTime);
    drawWaveform(frac);
  });
  $("#playBtn").addEventListener("click", togglePlay);
  $("#seekTrack").addEventListener("click", (e) => {
    const rect = e.target.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    if (audioEl.duration) audioEl.currentTime = frac * audioEl.duration;
  });

  // ---------------------------------------------------------- clip editor

  function fmtTimeMs(seconds) {
    if (!isFinite(seconds) || seconds < 0) seconds = 0;
    const m = Math.floor(seconds / 60);
    const s = seconds - m * 60;
    return `${m}:${s.toFixed(3).padStart(6, "0")}`;
  }

  async function openEditor() {
    if (!state.selectedFile || state.selectedSampleId == null) return;
    const ed = state.editor;
    ed.open = true;
    ed.clipId = null;
    ed.sampleId = state.selectedSampleId;
    ed.path = state.selectedFile.path;
    ed.name = state.selectedFile.name;
    ed.duration = state.waveformDuration || 0;
    ed.clipStart = 0;
    ed.clipEnd = ed.duration;
    ed.fadeInWidth = 0; ed.fadeInCpX = 0.5; ed.fadeInCpY = 0.5;
    ed.fadeOutWidth = 0; ed.fadeOutCpX = 0.5; ed.fadeOutCpY = 0.5;
    ed.viewStart = 0; ed.viewEnd = ed.duration;

    $("#editorPanel").style.display = "flex";
    $("#keybindsBrowse").style.display = "none";
    $("#keybindsEditor").style.display = "flex";
    $("#editorFileName").textContent = ed.name;
    $("#editorClipName").textContent = "New Clip";

    const waveform = await getJSON(`/api/sample/waveform?path=${encodeURIComponent(ed.path)}&bins=2000`);
    ed.peaks = waveform.peaks || [];
    if (!ed.duration) ed.duration = waveform.duration || 0;
    ed.clipEnd = ed.duration;
    ed.viewEnd = ed.duration;

    resizeEditorCanvases();
    drawEditor();
  }

  async function openEditorForClipId(clipId) {
    const clip = await getJSON(`/api/clips/${clipId}`);
    if (clip.error) return;
    await openEditor();
    const ed = state.editor;
    ed.clipId = clip.id;
    ed.clipStart = clip.start;
    ed.clipEnd = clip.end;
    ed.fadeInWidth = clip.fade_in_width; ed.fadeInCpX = clip.fade_in_cp_x; ed.fadeInCpY = clip.fade_in_cp_y;
    ed.fadeOutWidth = clip.fade_out_width; ed.fadeOutCpX = clip.fade_out_cp_x; ed.fadeOutCpY = clip.fade_out_cp_y;
    $("#editorClipName").textContent = clip.name;
    drawEditor();
  }

  function closeEditor() {
    const ed = state.editor;
    if (!ed.open) return;
    ed.open = false;
    audioEl.loop = false;
    $("#editorPanel").style.display = "none";
    $("#keybindsBrowse").style.display = "flex";
    $("#keybindsEditor").style.display = "none";
  }
  $("#editorCloseBtn").addEventListener("click", closeEditor);

  function resizeEditorCanvases() {
    const dpr = window.devicePixelRatio || 1;
    for (const id of ["editorCanvas", "minimapCanvas"]) {
      const c = $(`#${id}`);
      const w = c.clientWidth, h = c.clientHeight;
      c.width = w * dpr; c.height = h * dpr;
      c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }

  function editorColorAt(frac, dim) {
    const stops = [[139, 92, 246], [233, 79, 214], [251, 146, 60], [251, 191, 36]];
    const pos = Math.min(0.999, Math.max(0, frac)) * (stops.length - 1);
    const i = Math.floor(pos), t = pos - i;
    const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
    const r = a[0] + (b[0] - a[0]) * t, g = a[1] + (b[1] - a[1]) * t, bl = a[2] + (b[2] - a[2]) * t;
    return `rgba(${r | 0},${g | 0},${bl | 0},${dim ? 0.3 : 0.95})`;
  }

  // Quadratic bezier through (0,0)-(cpX,cpY)-(1,1), matching dsp.bezier_ease.
  function bezierEase(t, cpX, cpY) {
    let u = t;
    for (let i = 0; i < 5; i++) {
      const x = 2 * (1 - u) * u * cpX + u * u;
      const dx = 2 * cpX * (1 - 2 * u) + 2 * u || 1e-6;
      u = Math.max(0, Math.min(1, u - (x - t) / dx));
    }
    return 2 * (1 - u) * u * cpY + u * u;
  }

  function niceStep(span) {
    const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    for (const s of steps) if (span / s <= 10) return s;
    return steps[steps.length - 1];
  }

  function renderEditorRuler() {
    const ed = state.editor;
    const ruler = $("#editorRuler");
    ruler.innerHTML = "";
    const span = ed.viewEnd - ed.viewStart;
    if (span <= 0) return;
    const step = niceStep(span);
    const width = ruler.clientWidth;
    const start = Math.ceil(ed.viewStart / step) * step;
    for (let t = start; t <= ed.viewEnd; t += step) {
      const x = ((t - ed.viewStart) / span) * width;
      const label = document.createElement("span");
      label.style.left = `${x}px`;
      label.textContent = step < 1 ? t.toFixed(1) : t.toFixed(0);
      ruler.appendChild(label);
    }
  }

  function drawEditor() {
    const ed = state.editor;
    if (!ed.open || !ed.peaks) return;
    renderEditorRuler();

    const canvas = $("#editorCanvas");
    const ctx = canvas.getContext("2d");
    const width = canvas.clientWidth, height = canvas.clientHeight;
    ctx.clearRect(0, 0, width, height);

    const span = ed.viewEnd - ed.viewStart || 1;
    const n = ed.peaks.length;
    const mid = height / 2;
    const playFrac = audioEl.duration ? audioEl.currentTime / ed.duration : 0;
    const playX = ((playFrac * ed.duration - ed.viewStart) / span) * width;

    for (let i = 0; i < n; i++) {
      const t0 = (i / n) * ed.duration, t1 = ((i + 1) / n) * ed.duration;
      if (t1 < ed.viewStart || t0 > ed.viewEnd) continue;
      const x = ((t0 - ed.viewStart) / span) * width;
      const barW = Math.max(1, (ed.duration / n / span) * width);
      const [mn, mx] = ed.peaks[i];
      const inClip = t0 >= ed.clipStart && t0 <= ed.clipEnd;
      ctx.fillStyle = editorColorAt(i / n, !inClip);
      ctx.fillRect(x, mid - mx * mid * 0.9, barW, Math.max(1, (mx - mn) * mid * 0.9));
    }

    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(width, mid); ctx.stroke();

    // selection + fade overlay
    const sx = ((ed.clipStart - ed.viewStart) / span) * width;
    const ex = ((ed.clipEnd - ed.viewStart) / span) * width;
    const fiEndX = ((ed.clipStart + ed.fadeInWidth - ed.viewStart) / span) * width;
    const foStartX = ((ed.clipEnd - ed.fadeOutWidth - ed.viewStart) / span) * width;

    ctx.fillStyle = "rgba(233,79,214,0.10)";
    ctx.fillRect(Math.max(0, sx), 0, Math.min(width, ex) - Math.max(0, sx), height);

    ctx.strokeStyle = "rgba(233,79,214,0.9)";
    ctx.lineWidth = 1.5;
    for (const x of [sx, ex]) {
      if (x < 0 || x > width) continue;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
    }
    ctx.strokeStyle = "rgba(233,79,214,0.45)";
    for (const x of [fiEndX, foStartX]) {
      if (x < 0 || x > width) continue;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
    }

    // fade curves (drawn along the top edge)
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    ctx.lineWidth = 1.5;
    const topPad = 8;
    if (ed.fadeInWidth > 0 && fiEndX > 0) {
      ctx.beginPath();
      for (let px = Math.max(0, sx); px <= Math.min(width, fiEndX); px++) {
        const t = (px - sx) / Math.max(1, fiEndX - sx);
        const y = height - topPad - bezierEase(t, ed.fadeInCpX, ed.fadeInCpY) * (height - topPad * 2);
        px === Math.max(0, sx) ? ctx.moveTo(px, y) : ctx.lineTo(px, y);
      }
      ctx.stroke();
      drawHandle(ctx, fiEndX, height - topPad - ed.fadeInCpY * (height - topPad * 2));
    }
    if (ed.fadeOutWidth > 0 && foStartX < width) {
      ctx.beginPath();
      for (let px = Math.max(0, foStartX); px <= Math.min(width, ex); px++) {
        const t = (ex - px) / Math.max(1, ex - foStartX);
        const y = height - topPad - bezierEase(t, ed.fadeOutCpX, ed.fadeOutCpY) * (height - topPad * 2);
        px === Math.max(0, foStartX) ? ctx.moveTo(px, y) : ctx.lineTo(px, y);
      }
      ctx.stroke();
      drawHandle(ctx, foStartX, height - topPad - ed.fadeOutCpY * (height - topPad * 2));
    }

    // playhead
    if (playX >= 0 && playX <= width) {
      ctx.strokeStyle = "#4ade80";
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(playX, 0); ctx.lineTo(playX, height); ctx.stroke();
    }

    drawMinimap();
    $("#editorTime").textContent = `${fmtTimeMs(audioEl.currentTime || 0)} / ${fmtTimeMs(ed.duration)}`;
  }

  function drawHandle(ctx, x, y) {
    ctx.fillStyle = "#e94fd6";
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
  }

  function drawMinimap() {
    const ed = state.editor;
    const canvas = $("#minimapCanvas");
    const ctx = canvas.getContext("2d");
    const width = canvas.clientWidth, height = canvas.clientHeight;
    ctx.clearRect(0, 0, width, height);
    const n = ed.peaks.length;
    const mid = height / 2;
    for (let i = 0; i < n; i++) {
      const x = (i / n) * width;
      const [mn, mx] = ed.peaks[i];
      ctx.fillStyle = editorColorAt(i / n, false);
      ctx.fillRect(x, mid - mx * mid * 0.9, Math.max(1, width / n), Math.max(1, (mx - mn) * mid * 0.9));
    }
    const vs = (ed.viewStart / ed.duration) * width;
    const ve = (ed.viewEnd / ed.duration) * width;
    ctx.fillStyle = "rgba(255,255,255,0.12)";
    ctx.fillRect(0, 0, vs, height);
    ctx.fillRect(ve, 0, width - ve, height);
    ctx.strokeStyle = "rgba(255,255,255,0.6)";
    ctx.strokeRect(vs, 0, Math.max(1, ve - vs), height);
  }

  function editorXToTime(x, width) {
    const ed = state.editor;
    return ed.viewStart + (x / width) * (ed.viewEnd - ed.viewStart);
  }

  function hitHandle(x, targetX, tolerance = 7) {
    return Math.abs(x - targetX) <= tolerance;
  }

  const editorCanvasEl = document.getElementById("editorCanvas");

  editorCanvasEl.addEventListener("mousedown", (e) => {
    const ed = state.editor;
    if (!ed.open) return;
    const rect = editorCanvasEl.getBoundingClientRect();
    const width = rect.width;
    const x = e.clientX - rect.left;
    const span = ed.viewEnd - ed.viewStart;
    const sx = ((ed.clipStart - ed.viewStart) / span) * width;
    const ex = ((ed.clipEnd - ed.viewStart) / span) * width;
    const fiEndX = ((ed.clipStart + ed.fadeInWidth - ed.viewStart) / span) * width;
    const foStartX = ((ed.clipEnd - ed.fadeOutWidth - ed.viewStart) / span) * width;

    // A fresh/never-trimmed clip spans the whole file; don't let its
    // (non-existent) boundaries intercept clicks — every click should
    // start a brand new selection until the user has actually trimmed it.
    const hasRealSelection = (ed.clipEnd - ed.clipStart) < ed.duration - 1e-6;

    let mode;
    if (hasRealSelection && ed.fadeInWidth > 0 && hitHandle(x, fiEndX)) mode = "fade-in";
    else if (hasRealSelection && ed.fadeOutWidth > 0 && hitHandle(x, foStartX)) mode = "fade-out";
    else if (hasRealSelection && hitHandle(x, sx)) mode = "clip-start";
    else if (hasRealSelection && hitHandle(x, ex)) mode = "clip-end";
    else if (hasRealSelection && x > sx && x < ex) mode = "clip-move";
    else mode = "new-selection";

    ed.drag = {
      mode, startX: x, width,
      origClipStart: ed.clipStart, origClipEnd: ed.clipEnd,
      origFadeInCpY: ed.fadeInCpY, origFadeOutCpY: ed.fadeOutCpY,
    };
    if (mode === "new-selection") {
      ed.clipStart = ed.clipEnd = editorXToTime(x, width);
    }
  });

  document.addEventListener("mousemove", (e) => {
    const ed = state.editor;
    if (!ed.open || !ed.drag) return;
    const rect = editorCanvasEl.getBoundingClientRect();
    const height = rect.height;
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const y = Math.max(0, Math.min(height, e.clientY - rect.top));
    const d = ed.drag;
    const t = editorXToTime(x, d.width);

    if (d.mode === "new-selection" || d.mode === "clip-end") {
      ed.clipEnd = Math.max(ed.clipStart, t);
    } else if (d.mode === "clip-start") {
      ed.clipStart = Math.min(ed.clipEnd, t);
    } else if (d.mode === "clip-move") {
      const dt = editorXToTime(x, d.width) - editorXToTime(d.startX, d.width);
      const len = d.origClipEnd - d.origClipStart;
      let newStart = d.origClipStart + dt;
      newStart = Math.max(0, Math.min(ed.duration - len, newStart));
      ed.clipStart = newStart;
      ed.clipEnd = newStart + len;
    } else if (d.mode === "fade-in") {
      ed.fadeInWidth = Math.max(0, Math.min(ed.clipEnd - ed.clipStart, t - ed.clipStart));
      const topPad = 8;
      ed.fadeInCpY = Math.max(0, Math.min(1, 1 - (y - topPad) / (height - topPad * 2)));
    } else if (d.mode === "fade-out") {
      ed.fadeOutWidth = Math.max(0, Math.min(ed.clipEnd - ed.clipStart, ed.clipEnd - t));
      const topPad = 8;
      ed.fadeOutCpY = Math.max(0, Math.min(1, 1 - (y - topPad) / (height - topPad * 2)));
    }
    drawEditor();
  });

  document.addEventListener("mouseup", () => {
    if (state.editor.open) state.editor.drag = null;
  });

  editorCanvasEl.addEventListener("wheel", (e) => {
    const ed = state.editor;
    if (!ed.open) return;
    e.preventDefault();
    const rect = editorCanvasEl.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const centerTime = editorXToTime(x, rect.width);
    const span = ed.viewEnd - ed.viewStart;
    const factor = e.deltaY > 0 ? 1.2 : 1 / 1.2;
    const newSpan = Math.max(0.2, Math.min(ed.duration, span * factor));
    let newStart = centerTime - (centerTime - ed.viewStart) * (newSpan / span);
    newStart = Math.max(0, Math.min(ed.duration - newSpan, newStart));
    ed.viewStart = newStart;
    ed.viewEnd = newStart + newSpan;
    drawEditor();
  }, { passive: false });

  function panEditorTo(clientX) {
    const ed = state.editor;
    const rect = $("#minimapCanvas").getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const span = ed.viewEnd - ed.viewStart;
    let newStart = frac * ed.duration - span / 2;
    newStart = Math.max(0, Math.min(ed.duration - span, newStart));
    ed.viewStart = newStart;
    ed.viewEnd = newStart + span;
    drawEditor();
  }
  $("#minimapCanvas").addEventListener("mousedown", (e) => panEditorTo(e.clientX));
  $("#minimapCanvas").addEventListener("mousemove", (e) => { if (e.buttons === 1) panEditorTo(e.clientX); });
  $("#minimapLeft").addEventListener("click", () => {
    const ed = state.editor; const span = ed.viewEnd - ed.viewStart;
    ed.viewStart = Math.max(0, ed.viewStart - span * 0.5);
    ed.viewEnd = ed.viewStart + span;
    drawEditor();
  });
  $("#minimapRight").addEventListener("click", () => {
    const ed = state.editor; const span = ed.viewEnd - ed.viewStart;
    ed.viewEnd = Math.min(ed.duration, ed.viewEnd + span * 0.5);
    ed.viewStart = ed.viewEnd - span;
    drawEditor();
  });

  window.addEventListener("resize", () => { if (state.editor.open) { resizeEditorCanvases(); drawEditor(); } });

  function editorPlayToggle() {
    const ed = state.editor;
    if (audioEl.paused) {
      if (audioEl.currentTime < ed.clipStart || audioEl.currentTime >= ed.clipEnd) {
        audioEl.currentTime = ed.clipStart;
      }
      audioEl.play().catch(() => {});
    } else {
      audioEl.pause();
    }
  }
  $("#editorPlayBtn").addEventListener("click", editorPlayToggle);
  $("#editorLoopBtn").addEventListener("click", () => {
    state.editor.loop = !state.editor.loop;
    $("#editorLoopBtn").classList.toggle("active", state.editor.loop);
  });
  $("#editorLoopBtn").classList.add("active");

  audioEl.addEventListener("timeupdate", () => {
    const ed = state.editor;
    if (!ed.open) return;
    $("#editorPlayIcon").innerHTML = audioEl.paused
      ? '<path fill="currentColor" d="M8 5v14l11-7z"/>'
      : '<path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z"/>';
    if (!audioEl.paused && audioEl.currentTime >= ed.clipEnd) {
      if (ed.loop) audioEl.currentTime = ed.clipStart;
      else audioEl.pause();
    }
    drawEditor();
  });

  async function saveClip() {
    const ed = state.editor;
    const body = {
      sample_id: ed.sampleId,
      name: $("#editorClipName").textContent || "Clip",
      start: ed.clipStart, end: ed.clipEnd,
      fade_in_width: ed.fadeInWidth, fade_in_cp_x: ed.fadeInCpX, fade_in_cp_y: ed.fadeInCpY,
      fade_out_width: ed.fadeOutWidth, fade_out_cp_x: ed.fadeOutCpX, fade_out_cp_y: ed.fadeOutCpY,
    };
    if (ed.clipId) {
      await fetch(`/api/clips/${ed.clipId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
    } else {
      if (body.name === "New Clip") {
        const count = (await getJSON(`/api/clips?sample_id=${ed.sampleId}`)).clips.length + 1;
        body.name = `${ed.name.replace(/\.[^.]+$/, "")}-CUT${count}`;
        $("#editorClipName").textContent = body.name;
      }
      const res = await postJSON("/api/clips", body);
      ed.clipId = res.id;
      await postJSON("/api/sets/toggle_clip_member", { clip_id: ed.clipId, set_id: state.activeSetId });
      await refreshSets();
    }
  }
  $("#editorSaveBtn").addEventListener("click", saveClip);

  $("#editorRenameBtn").addEventListener("click", async () => {
    const ed = state.editor;
    const name = prompt("Clip name:", $("#editorClipName").textContent);
    if (!name) return;
    $("#editorClipName").textContent = name;
    if (ed.clipId) {
      await fetch(`/api/clips/${ed.clipId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
      });
      await refreshSetMembers();
    }
  });

  $("#editorDeleteBtn").addEventListener("click", async () => {
    const ed = state.editor;
    if (!ed.clipId) { closeEditor(); return; }
    if (!confirm(`Delete clip "${$("#editorClipName").textContent}"?`)) return;
    await fetch(`/api/clips/${ed.clipId}`, { method: "DELETE" });
    closeEditor();
    await refreshSets();
  });

  function handleEditorKey(e) {
    const ed = state.editor;
    switch (e.key) {
      case " ":
        e.preventDefault();
        editorPlayToggle();
        break;
      case "ArrowLeft":
        e.preventDefault();
        if (e.shiftKey) { ed.clipEnd = Math.max(ed.clipStart + 0.01, ed.clipEnd - 0.01); drawEditor(); }
        else audioEl.currentTime = Math.max(0, audioEl.currentTime - 1);
        break;
      case "ArrowRight":
        e.preventDefault();
        if (e.shiftKey) { ed.clipEnd = Math.min(ed.duration, ed.clipEnd + 0.01); drawEditor(); }
        else audioEl.currentTime = Math.min(ed.duration, audioEl.currentTime + 1);
        break;
      case "Backspace":
        e.preventDefault();
        ed.clipStart = 0; ed.clipEnd = ed.duration;
        ed.fadeInWidth = 0; ed.fadeOutWidth = 0;
        drawEditor();
        break;
      case "Escape":
        closeEditor();
        break;
    }
  }

  $("#editorExportBtn").addEventListener("click", async () => {
    const ed = state.editor;
    const destination = prompt("Export clip to folder (blank = default):", "");
    if (destination === null) return;
    const result = await postJSON("/api/export_clip", {
      path: ed.path, start: ed.clipStart, end: ed.clipEnd,
      name: $("#editorClipName").textContent, destination: destination || null,
    });
    alert(result.error ? `Export failed: ${result.error}` : `Exported to ${result.destination}`);
  });

  // ---------------------------------------------------------- sets

  async function refreshSets() {
    const data = await getJSON("/api/sets");
    state.sets = data.sets;
    state.activeSetId = data.active_set_id;
    renderSetBadge();
    await refreshSetMembers();
  }

  function renderSetBadge() {
    const active = state.sets.find(s => s.id === state.activeSetId) || { name: "—", count: 0 };
    $("#activeSetName").textContent = active.name;
    $("#activeSetCount").textContent = `(${active.count})`;
    $("#setHeaderName").textContent = active.name;
    $("#setClearCount").textContent = active.count;
  }

  async function refreshSetMembers() {
    const data = await getJSON(`/api/sets/${state.activeSetId}/members`);
    state.setMembers = data.members;
    renderSetList();
  }

  function renderSetList() {
    const container = $("#setList");
    container.innerHTML = "";
    state.setMembers.forEach((m, i) => {
      const isClip = m.kind === "clip";
      const row = document.createElement("div");
      row.className = "row" + (i === state.setSelectedIndex && state.pane === "set" ? " selected" : "");
      row.innerHTML = `
        <span class="row-icon"><svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg></span>
        <span class="row-name">${escapeHtml(m.display_name || m.name)}</span>
        <span class="row-meta">${fmtDuration(m.duration)}</span>
        <span class="row-meta size${isClip ? " clip" : ""}">${isClip ? "CLIP" : fmtSize(m.size)}</span>`;
      row.addEventListener("click", () => {
        state.setSelectedIndex = i;
        state.pane = "set";
        renderSetList();
        if (isClip) {
          selectFile({ path: m.path, name: m.name }, { keepEditor: true }).then(() =>
            openEditorForClipId(m.clip_id)
          );
        } else {
          selectFile({ path: m.path, name: m.name });
        }
      });
      container.appendChild(row);
    });
  }

  async function toggleActiveSetMember(path) {
    await postJSON("/api/sets/toggle_member", { path, set_id: state.activeSetId });
    await browse(state.path);
    await refreshSets();
  }

  async function cycleActiveSet() {
    if (!state.sets.length) return;
    const idx = state.sets.findIndex(s => s.id === state.activeSetId);
    const next = state.sets[(idx + 1) % state.sets.length];
    await postJSON("/api/sets/active", { set_id: next.id });
    await refreshSets();
    await browse(state.path);
  }

  $("#activeSetBadge").addEventListener("click", cycleActiveSet);
  $("#clearSetBtn").addEventListener("click", async () => {
    for (const m of [...state.setMembers]) {
      if (m.kind === "clip") {
        await postJSON("/api/sets/toggle_clip_member", { clip_id: m.clip_id, set_id: state.activeSetId });
      } else {
        await postJSON("/api/sets/toggle_member", { path: m.path, set_id: state.activeSetId });
      }
    }
    await refreshSets();
    await browse(state.path);
  });

  // ---------------------------------------------------------- search

  let searchDebounce = null;
  $("#searchInput").addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    const q = e.target.value;
    searchDebounce = setTimeout(() => filterCurrentView(q), 150);
  });
  $("#searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") deepSearch(e.target.value);
    e.stopPropagation();
  });

  function filterCurrentView(q) {
    const rows = document.querySelectorAll("#fileList .row");
    const list = combinedList();
    rows.forEach((row, i) => {
      const name = (list[i] && list[i].name || "").toLowerCase();
      row.style.display = !q || name.includes(q.toLowerCase()) ? "" : "none";
    });
  }

  async function deepSearch(q) {
    if (!q) return browse(state.path);
    const data = await getJSON(`/api/filter?path=${encodeURIComponent(state.path)}&q=${encodeURIComponent(q)}`);
    state.folders = [];
    state.files = data.files;
    state.selectedIndex = state.files.length ? 0 : -1;
    $("#itemCount").textContent = `${data.total} matches`;
    renderFileList();
  }

  // ---------------------------------------------------------- toolbar

  $("#autoToggle").addEventListener("click", () => {
    state.autoplay = !state.autoplay;
    $("#autoToggle").classList.toggle("pill-active", state.autoplay);
    $("#autoToggle").innerHTML = `Auto: <b>${state.autoplay ? "ON" : "OFF"}</b>`;
  });

  $("#openFolderBtn").addEventListener("click", () => {
    const p = prompt("Folder path to browse:", state.path || "");
    if (p) browse(p);
  });

  $("#helpBtn").addEventListener("click", () => openHelp());
  $("#closeHelpBtn").addEventListener("click", () => closeModals());
  $("#settingsBtn").addEventListener("click", () => openSettings());
  $("#closeSettingsBtn").addEventListener("click", () => closeModals());
  $("#logsLink").addEventListener("click", () => alert("Logs — not yet implemented in this recreation."));

  const HELP_ENTRIES = [
    ["Space", "Play / Stop"], ["P", "Toggle autoplay"], ["↑ / ↓", "Navigate list"],
    ["A / D", "Up / into folder"], ["E", "Add / remove from active set"],
    ["Tab", "Switch pane"], ["V", "View mode (clip editor)"], ["Q", "Switch active set"],
    ["X", "Export active set"], ["?", "Toggle this help"], ["Esc", "Close dialog"],
  ];
  function openHelp() {
    $("#helpGrid").innerHTML = HELP_ENTRIES.map(([k, d]) => `<kbd>${k}</kbd><span>${d}</span>`).join("");
    $("#helpModalBackdrop").classList.add("open");
  }
  function closeModals() {
    $("#helpModalBackdrop").classList.remove("open");
    $("#exportModalBackdrop").classList.remove("open");
    $("#settingsModalBackdrop").classList.remove("open");
  }

  // ---------------------------------------------------------- settings

  async function openSettings() {
    const meta = await getJSON("/api/meta");
    $("#dbPathLabel").textContent = meta.db_path;

    const prefs = await getJSON("/api/preferences");
    const vol = prefs.master_volume != null ? parseFloat(prefs.master_volume) : 1.0;
    audioEl.volume = vol;
    $("#volumeSlider").value = Math.round(vol * 100);
    $("#volumeValue").textContent = `${Math.round(vol * 100)}%`;

    await refreshPresetList();
    $("#presetFormContainer").innerHTML = "";
    $("#settingsModalBackdrop").classList.add("open");
  }

  $("#volumeSlider").addEventListener("input", (e) => {
    const v = parseInt(e.target.value, 10) / 100;
    audioEl.volume = v;
    $("#volumeValue").textContent = `${e.target.value}%`;
  });
  $("#volumeSlider").addEventListener("change", (e) => {
    postJSON("/api/preferences", { key: "master_volume", value: parseInt(e.target.value, 10) / 100 });
  });

  const PRESET_FORM_FIELDS = [
    ["name", "text", "Name"],
    ["convert_to_mono", "bool", "Convert to mono"],
    ["mono_mode", "select:sum,left,right", "Mono mode"],
    ["normalize", "bool", "Normalize"],
    ["normalize_ceiling", "number", "Ceiling (dB)"],
    ["limit_enabled", "bool", "Limiter"],
    ["limit_threshold", "number", "Threshold (dB)"],
    ["high_pass_enabled", "bool", "High-pass"],
    ["high_pass_frequency", "number", "HP freq (Hz)"],
    ["sample_rate_enabled", "bool", "Resample"],
    ["sample_rate_target", "number", "Target Hz"],
    ["bit_depth_enabled", "bool", "Bit depth"],
    ["bit_depth_target", "select:16,24,32", "Target bits"],
    ["prefix_with_number", "bool", "Prefix with number"],
    ["generate_manifest", "bool", "Generate manifest.txt"],
    ["legacy_wav", "bool", "Legacy WAV header"],
    ["append_cue", "bool", "Append cue point"],
    ["post_export_command_enabled", "bool", "Run command after export"],
    ["post_export_command", "text", "Command"],
  ];

  async function refreshPresetList() {
    const data = await getJSON("/api/presets");
    const container = $("#presetList");
    container.innerHTML = "";
    if (!data.presets.length) {
      container.innerHTML = `<div style="color:var(--text-faint);font-size:12px">No saved presets yet.</div>`;
    }
    data.presets.forEach(p => {
      const row = document.createElement("div");
      row.className = "preset-row";
      row.innerHTML = `
        <span class="preset-name">${escapeHtml(p.name)}</span>
        <button data-action="edit">&#9998;</button>
        <button data-action="delete">&#128465;</button>`;
      row.querySelector('[data-action="edit"]').addEventListener("click", () => renderPresetForm(p));
      row.querySelector('[data-action="delete"]').addEventListener("click", async () => {
        if (confirm(`Delete preset "${p.name}"?`)) {
          await fetch(`/api/presets/${p.id}`, { method: "DELETE" });
          await refreshPresetList();
        }
      });
      container.appendChild(row);
    });
  }

  function renderPresetForm(preset) {
    const isNew = !preset;
    const p = preset || { ...PRESET_FORM_DEFAULTS() };
    const container = $("#presetFormContainer");
    const form = document.createElement("div");
    form.className = "preset-form";
    for (const [key, type, label] of PRESET_FORM_FIELDS) {
      const wrap = document.createElement("label");
      if (type === "text" && key === "post_export_command") wrap.classList.add("full-row");
      if (type === "bool") {
        wrap.innerHTML = `<input type="checkbox" data-key="${key}" ${p[key] ? "checked" : ""}> ${label}`;
      } else if (type.startsWith("select:")) {
        const opts = type.split(":")[1].split(",");
        wrap.innerHTML = `${label}: <select data-key="${key}">${opts.map(o => `<option value="${o}" ${String(p[key]) === o ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      } else {
        wrap.innerHTML = `${label}: <input type="${type}" data-key="${key}" value="${p[key] ?? ""}" step="any">`;
      }
      form.appendChild(wrap);
    }
    const actions = document.createElement("div");
    actions.className = "preset-form-actions";
    actions.innerHTML = `<button class="pill" id="cancelPresetForm">Cancel</button><button class="pill pill-active" id="savePresetForm">${isNew ? "Create" : "Save"}</button>`;
    form.appendChild(actions);

    container.innerHTML = "";
    container.appendChild(form);

    form.querySelector("#cancelPresetForm").addEventListener("click", () => { container.innerHTML = ""; });
    form.querySelector("#savePresetForm").addEventListener("click", async () => {
      const body = {};
      form.querySelectorAll("[data-key]").forEach(el => {
        const key = el.dataset.key;
        if (el.type === "checkbox") body[key] = el.checked;
        else if (el.tagName === "SELECT") body[key] = isNaN(el.value) ? el.value : Number(el.value);
        else body[key] = el.type === "number" ? parseFloat(el.value) : el.value;
      });
      if (isNew) await postJSON("/api/presets", body);
      else await fetch(`/api/presets/${preset.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      container.innerHTML = "";
      await refreshPresetList();
    });
  }
  function PRESET_FORM_DEFAULTS() {
    return {
      name: "New Preset", convert_to_mono: false, mono_mode: "sum", normalize: false,
      normalize_ceiling: -0.3, limit_enabled: false, limit_threshold: -0.3,
      high_pass_enabled: false, high_pass_frequency: 80, sample_rate_enabled: false,
      sample_rate_target: 44100, bit_depth_enabled: false, bit_depth_target: 16,
      prefix_with_number: false, generate_manifest: false, legacy_wav: false,
      append_cue: false, post_export_command_enabled: false, post_export_command: "",
    };
  }
  $("#newPresetBtn").addEventListener("click", () => renderPresetForm(null));

  // ---------------------------------------------------------- export modal

  async function openExport() {
    $("#exportOptions").innerHTML = `
      <label>Preset
        <select id="exportPresetSelect" style="margin-left:8px;background:#1c1c24;color:var(--text);border:1px solid var(--border);border-radius:6px;font-family:var(--mono);padding:3px 6px;">
          <option value="">Custom</option>
        </select>
      </label>
      <div id="exportCustomOptions">
        <label><input type="checkbox" id="optMono"> Convert to mono (sum)</label>
        <label><input type="checkbox" id="optNormalize" checked> Normalize to -0.3 dB</label>
        <label><input type="checkbox" id="optManifest" checked> Generate manifest.txt</label>
        <label><input type="checkbox" id="optLegacy"> Legacy WAV header</label>
        <label><input type="checkbox" id="optCue"> Append cue point</label>
      </div>
    `;
    const data = await getJSON("/api/presets");
    const select = $("#exportPresetSelect");
    data.presets.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id; opt.textContent = p.name;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => {
      $("#exportCustomOptions").style.opacity = select.value ? "0.4" : "1";
      $("#exportCustomOptions").style.pointerEvents = select.value ? "none" : "auto";
    });
    $("#exportResult").textContent = "";
    $("#exportModalBackdrop").classList.add("open");
  }
  $("#runExportBtn").addEventListener("click", async () => {
    const presetId = $("#exportPresetSelect").value;
    const body = presetId
      ? { set_id: state.activeSetId, preset_id: parseInt(presetId, 10) }
      : {
          set_id: state.activeSetId,
          mono: $("#optMono").checked,
          normalize: $("#optNormalize").checked,
          manifest: $("#optManifest").checked,
          legacy_wav: $("#optLegacy").checked,
          cue: $("#optCue").checked,
        };
    $("#exportResult").textContent = "Exporting...";
    const result = await postJSON("/api/export", body);
    $("#exportResult").textContent =
      `Exported ${result.copied} file(s) to:\n${result.destination}` +
      (result.failed && result.failed.length ? `\n\nFailed:\n${result.failed.map(f => f.path + ": " + f.reason).join("\n")}` : "");
  });
  $("#cancelExportBtn").addEventListener("click", closeModals);

  // ---------------------------------------------------------- keyboard

  document.addEventListener("keydown", (e) => {
    if (document.activeElement === $("#searchInput")) {
      if (e.key === "Escape") { $("#searchInput").blur(); filterCurrentView(""); }
      return;
    }
    if ($("#helpModalBackdrop").classList.contains("open") || $("#exportModalBackdrop").classList.contains("open")
        || $("#settingsModalBackdrop").classList.contains("open")) {
      if (e.key === "Escape") closeModals();
      return;
    }

    if (state.editor.open) {
      handleEditorKey(e);
      return;
    }

    switch (e.key) {
      case " ":
        e.preventDefault();
        togglePlay();
        break;
      case "p": case "P":
        $("#autoToggle").click();
        break;
      case "v": case "V":
        openEditor();
        break;
      case "ArrowUp":
        e.preventDefault();
        moveSelection(-1);
        break;
      case "ArrowDown":
        e.preventDefault();
        moveSelection(1);
        break;
      case "a": case "A":
        if (state.breadcrumbs.length > 1) {
          browse(state.breadcrumbs[state.breadcrumbs.length - 2].path);
        }
        break;
      case "d": case "D": {
        const list = combinedList();
        const sel = list[state.selectedIndex];
        if (sel && sel._kind === "folder") browse(sel.path);
        break;
      }
      case "e": case "E": {
        const list = combinedList();
        const sel = list[state.selectedIndex];
        if (sel && sel._kind === "file") toggleActiveSetMember(sel.path);
        break;
      }
      case "Tab":
        e.preventDefault();
        state.pane = state.pane === "browser" ? "set" : state.pane === "set" ? "detail" : "browser";
        break;
      case "q": case "Q":
        cycleActiveSet();
        break;
      case "x": case "X":
        openExport();
        break;
      case "?":
        openHelp();
        break;
      case "/":
        e.preventDefault();
        $("#searchInput").focus();
        break;
    }
  });

  function moveSelection(delta) {
    if (state.pane === "set") {
      state.setSelectedIndex = Math.max(0, Math.min(state.setMembers.length - 1, state.setSelectedIndex + delta));
      renderSetList();
      const m = state.setMembers[state.setSelectedIndex];
      if (m) selectFile({ path: m.path, name: m.name });
      return;
    }
    const list = combinedList();
    if (!list.length) return;
    state.selectedIndex = Math.max(0, Math.min(list.length - 1, state.selectedIndex + delta));
    renderFileList();
    const entry = list[state.selectedIndex];
    if (entry._kind === "file") selectFile(entry);
    const row = document.querySelector(`#fileList .row[data-index="${state.selectedIndex}"]`);
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------------------------------------------------- boot

  (async function init() {
    await refreshSets();
    await browse(null);
  })();
})();
