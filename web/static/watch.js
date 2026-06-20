function getEpisodeId() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] || "");
}

function shouldPrepare() {
  return new URLSearchParams(window.location.search).get("prepare") === "1";
}

let pollTimer = null;
let episodeData = null;
let playerBound = false;

function setPanelVisible(el, visible) {
  if (!el) return;
  el.hidden = !visible;
  el.classList.toggle("hidden", !visible);
}

function showPanel(name) {
  setPanelVisible(document.getElementById("processing-panel"), name === "processing");
  setPanelVisible(document.getElementById("player-panel"), name === "player");
  setPanelVisible(document.getElementById("idle-panel"), name === "idle");
  setPanelVisible(document.getElementById("error-panel"), name === "error");
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

function updateVideoMeta(player) {
  const metaEl = document.getElementById("video-meta");
  if (!metaEl || !player.videoWidth) return;
  metaEl.textContent = `${player.videoWidth}×${player.videoHeight} · ${formatDuration(player.duration)}`;
}

function setSubtitlesEnabled(enabled) {
  const player = document.getElementById("player");
  const toggleBtn = document.getElementById("subtitle-toggle");
  const track = player?.textTracks?.[0];
  if (track) {
    track.mode = enabled ? "showing" : "hidden";
  }
  if (toggleBtn) {
    toggleBtn.setAttribute("aria-pressed", enabled ? "true" : "false");
    toggleBtn.classList.toggle("text-neutral-500", !enabled);
    toggleBtn.classList.toggle("border-neutral-800/60", !enabled);
  }
}

function bindPlayerControls() {
  if (playerBound) return;

  const player = document.getElementById("player");
  const subtitleBtn = document.getElementById("subtitle-toggle");

  player.addEventListener("loadedmetadata", () => updateVideoMeta(player));

  subtitleBtn?.addEventListener("click", () => {
    const track = player.textTracks[0];
    setSubtitlesEnabled(track?.mode !== "showing");
  });

  playerBound = true;
}

function updateProcessingUI(episode) {
  const progress = Math.round((episode.progress || 0) * 100);
  document.getElementById("processing-bar").style.width = `${progress}%`;
  document.getElementById("processing-message").textContent =
    episode.progressMessage || "İşlem devam ediyor…";
}

function showProcessingState({ title = "Hazırlanıyor", message = "…", showProgress = true } = {}) {
  document.getElementById("processing-title").textContent = title;
  document.getElementById("processing-message").textContent = message;
  document.getElementById("processing-spinner").hidden = false;
  document.getElementById("processing-spinner").classList.remove("hidden");
  document.getElementById("processing-progress-wrap").hidden = !showProgress;
  document.getElementById("processing-progress-wrap").classList.toggle("hidden", !showProgress);
  showPanel("processing");
}

async function rebuildEpisode(episodeId, { keepVideo = false } = {}) {
  const msg = keepVideo
    ? "Altyazılar silinip yeniden oluşturulacak (video korunur)."
    : "Tüm çıktılar silinip baştan oluşturulacak.";
  if (!window.confirm(`${msg}\n\nDevam edilsin mi?`)) return null;

  const res = await fetch(`/api/episodes/${encodeURIComponent(episodeId)}/rebuild`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keepVideo, autoStart: true }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Yeniden oluşturulamadı");
  }
  return res.json();
}

async function startProcessing(episodeId) {
  const res = await fetch(`/api/episodes/${encodeURIComponent(episodeId)}/process`, {
    method: "POST",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "İşlem başlatılamadı");
  }
  return res.json();
}

async function fetchEpisode(episodeId) {
  const res = await fetch(`/api/episodes/${encodeURIComponent(episodeId)}`);
  if (!res.ok) throw new Error("Bölüm bulunamadı");
  return res.json();
}

function mountPlayer(episodeId) {
  bindPlayerControls();

  const player = document.getElementById("player");
  const track = player.querySelector("track");

  document.getElementById("video-meta").textContent = "";
  player.src = `/media/${encodeURIComponent(episodeId)}?t=${Date.now()}`;
  track.src = `/subs/${encodeURIComponent(episodeId)}/tr.vtt?t=${Date.now()}`;
  player.load();
  setSubtitlesEnabled(true);
  showPanel("player");
}

async function pollUntilReady(episodeId) {
  showProcessingState();
  pollTimer = setInterval(async () => {
    try {
      const episode = await fetchEpisode(episodeId);
      episodeData = episode;
      updateProcessingUI(episode);

      if (episode.status === "ready" || episode.hasSubtitles) {
        clearInterval(pollTimer);
        pollTimer = null;
        mountPlayer(episodeId);
        document.getElementById("episode-status").textContent = "Türkçe altyazı hazır";
      } else if (episode.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
        document.getElementById("error-message").textContent = episode.error || "Bilinmeyen hata";
        showPanel("error");
      }
    } catch (err) {
      console.error(err);
    }
  }, 2000);
}

async function runRebuild(episodeId) {
  try {
    await rebuildEpisode(episodeId, { keepVideo: false });
    document.getElementById("episode-status").textContent = "Yeniden oluşturuluyor…";
    await pollUntilReady(episodeId);
  } catch (err) {
    document.getElementById("error-message").textContent = String(err.message || err);
    showPanel("error");
  }
}

async function initWatchPage() {
  const episodeId = getEpisodeId();
  const titleEl = document.getElementById("episode-title");
  const statusEl = document.getElementById("episode-status");

  showProcessingState({
    title: "Yükleniyor",
    message: "Bölüm bilgisi alınıyor…",
    showProgress: false,
  });

  document.getElementById("retry-btn").addEventListener("click", () => runRebuild(episodeId));
  document.getElementById("rebuild-btn")?.addEventListener("click", () => runRebuild(episodeId));

  try {
    episodeData = await fetchEpisode(episodeId);
    titleEl.textContent = episodeData.title || episodeId;
    statusEl.textContent = episodeData.videoName || "";

    if (episodeData.status === "ready" || episodeData.hasSubtitles) {
      mountPlayer(episodeId);
      statusEl.textContent = "Türkçe altyazı hazır";
      return;
    }

    if (episodeData.status === "failed") {
      document.getElementById("error-message").textContent = episodeData.error || "İşlem başarısız";
      showPanel("error");
      return;
    }

    if (episodeData.status === "processing" || shouldPrepare()) {
      if (shouldPrepare() && episodeData.status !== "processing") {
        await startProcessing(episodeId);
      }
      updateProcessingUI(episodeData);
      showProcessingState();
      await pollUntilReady(episodeId);
      return;
    }

    if (shouldPrepare()) {
      await startProcessing(episodeId);
      await pollUntilReady(episodeId);
      return;
    }

    showPanel("idle");
  } catch (err) {
    titleEl.textContent = "Yükleme hatası";
    document.getElementById("error-message").textContent = String(err.message || err);
    showPanel("error");
  }
}

initWatchPage();
