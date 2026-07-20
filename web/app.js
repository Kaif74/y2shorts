const STAGES = [["fetch_transcript", "Transcript"], ["llm_ranking", "Ranking"], ["download_video", "Download"], ["clipping", "Clipping"], ["reframing", "Vertical crop"], ["captioning", "Captions"], ["done", "Done"]];
const state = { job: null, socket: null, stageEvents: new Map() };
const $ = (selector) => document.querySelector(selector);
const validUrl = (value) => /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\//i.test(value.trim());

function renderProgress() {
  const list = $("#progress-list"), template = $("#stage-template"); list.replaceChildren(); let active = false;
  STAGES.forEach(([key, label]) => {
    const event = state.stageEvents.get(key), item = template.content.firstElementChild.cloneNode(true);
    item.querySelector("strong").textContent = label; item.querySelector("small").textContent = event?.detail || "Waiting";
    const status = item.querySelector(".stage-state"); status.textContent = event?.status === "done" ? "Complete" : event?.status === "error" ? "Issue" : event?.status === "in_progress" ? "Working" : "";
    if (event?.status === "done") item.classList.add("done");
    else if (event?.status === "error") item.classList.add("stage-error");
    else if (event?.status === "in_progress" || (!active && state.job?.status === "running" && !event)) { item.classList.add("active"); active = true; }
    list.append(item);
  });
  const latest = [...state.stageEvents.values()].at(-1); $("#active-detail").textContent = latest?.detail || "Setting up your job…";
}

function renderResults(job) {
  const clips = [...(job.result?.clips || [])].sort((a, b) => a.rank - b.rank), grid = $("#clip-grid"); grid.replaceChildren();
  clips.forEach((clip) => {
    const card = document.createElement("article"); card.className = "clip";
    const video = document.createElement("video"); video.controls = true; video.playsInline = true; video.preload = "metadata"; video.src = clip.video_url; card.append(video);
    const body = document.createElement("div"); body.className = "clip-body";
    const top = document.createElement("div"); top.className = "clip-top";
    const rank = document.createElement("span"); rank.className = "rank"; rank.textContent = `RANK ${clip.rank}`;
    const score = document.createElement("span"); score.className = "score"; score.textContent = `${Math.round(clip.score)} SCORE`; top.append(rank, score); body.append(top);
    const title = document.createElement("h3"); title.textContent = clip.viral_title; body.append(title);
    const meta = document.createElement("p"); meta.className = "meta"; meta.textContent = `${Number(clip.duration).toFixed(1)} seconds · ${Number(clip.start).toFixed(1)}s in source`; body.append(meta);
    const reason = document.createElement("p"); reason.className = "reason"; reason.textContent = clip.reason; body.append(reason);
    const alts = document.createElement("div"); alts.className = "alts"; (clip.alt_titles || []).forEach((text) => { const tag = document.createElement("span"); tag.textContent = text; alts.append(tag); }); body.append(alts);
    const download = document.createElement("a"); download.className = "download"; download.href = `${clip.video_url}?download=true`; download.textContent = "Download MP4 ↓"; body.append(download); card.append(body); grid.append(card);
  });
  $("#results-summary").textContent = `${clips.length} ready`; $("#results").hidden = false;
}

function applyJob(job) {
  state.job = job; state.stageEvents = new Map(); (job.events || []).forEach((event) => { if (event.stage !== "error") state.stageEvents.set(event.stage, event); });
  $("#workspace").hidden = false; $("#job-title").textContent = job.status === "done" ? "Your clips are ready" : "Making your short-form cut"; $("#job-status").textContent = job.status;
  $("#error-panel").hidden = job.status !== "error"; if (job.error) $("#error-message").textContent = job.error; renderProgress();
  if (job.status === "done") renderResults(job); else $("#results").hidden = true;
}

function handleEvent(event) {
  if (event.stage === "snapshot") { applyJob(event.job); renderHistory(); return; }
  if (event.stage === "error") { $("#error-panel").hidden = false; $("#error-message").textContent = event.detail; $("#job-status").textContent = "error"; }
  else state.stageEvents.set(event.stage, event); renderProgress();
}

function openSocket(job) {
  state.socket?.close(); const protocol = location.protocol === "https:" ? "wss" : "ws"; const after = job.events?.length || 0;
  const socket = new WebSocket(`${protocol}://${location.host}/jobs/${job.id}/ws?after=${after}`); state.socket = socket;
  socket.onmessage = (message) => handleEvent(JSON.parse(message.data));
  socket.onclose = () => { if (state.job?.status === "running") setTimeout(() => refreshJob(job.id), 900); };
}

async function refreshJob(id) { try { const response = await fetch(`/jobs/${id}`); if (!response.ok) return; const job = await response.json(); applyJob(job); if (job.status === "running") openSocket(job); renderHistory(); } catch (_) {} }
async function renderHistory() {
  try { const response = await fetch("/jobs"); if (!response.ok) return; const { jobs } = await response.json(), list = $("#history-list"); list.replaceChildren(); $("#history-section").hidden = !jobs.length;
    jobs.slice(0, 8).forEach((job) => { const button = document.createElement("button"); button.className = "history"; const url = document.createElement("span"); url.textContent = job.url; const status = document.createElement("small"); status.textContent = job.status; button.append(url, status); button.onclick = () => { applyJob(job); if (job.status === "running") openSocket(job); }; list.append(button); });
  } catch (_) {}
}

$("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const url = $("#youtube-url").value.trim(), error = $("#form-error"), button = $("#job-form button"); error.textContent = "";
  if (!validUrl(url)) { error.textContent = "Enter a valid YouTube or youtu.be link."; return; }
  button.disabled = true; button.textContent = "Starting…";
  try { const response = await fetch("/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) }); const job = await response.json(); if (!response.ok) throw new Error(job.detail || "Could not start the job."); applyJob(job); openSocket(job); renderHistory(); }
  catch (failure) { error.textContent = failure.message; }
  finally { button.disabled = false; button.innerHTML = "Make clips <b>↗</b>"; }
});
renderHistory();
