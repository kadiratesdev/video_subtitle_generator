function getEpisodeId() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] || "");
}

function shouldPrepare() {
  return new URLSearchParams(window.location.search).get("prepare") === "1";
}

let pollTimer = null;
let episodeData = null;

function showPanel(name) {
  document.getElementById("processing-panel").hidden = name !== "processing";
  document.getElementById("player-panel").hidden = name !== "player";
  document.getElementById("error-panel").hidden = name !== "error";
}

function updateProcessingUI(episode) {
  const progress = Math.round((episode.progress || 0) * 100);
  document.getElementById("processing-bar").style.width = `${progress}%`;
  document.getElementById("processing-message").textContent =
    episode.progressMessage || "İşlem devam ediyor...";
}

async function rebuildEpisode(episodeId, { keepVideo = false } = {}) {
  const msg = keepVideo
    ? "Altyazılar silinip yeniden oluşturulacak (video korunur)."
    : "Tüm çıktılar silinip baştan oluşturulacak.";
  if (!window.confirm(`${msg}\n\nDevam edilsin mi?`)) {
    return null;
  }

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
  if (!res.ok) {
    throw new Error("Bölüm bulunamadı");
  }
  return res.json();
}

function mountPlayer(episodeId) {
  const player = document.getElementById("player");
  const track = player.querySelector("track");
  player.src = `/media/${encodeURIComponent(episodeId)}?t=${Date.now()}`;
  track.src = `/subs/${encodeURIComponent(episodeId)}/tr.vtt?t=${Date.now()}`;
  player.load();
  showPanel("player");
}

async function pollUntilReady(episodeId) {
  showPanel("processing");
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
  const retryBtn = document.getElementById("retry-btn");
  const rebuildBtn = document.getElementById("rebuild-btn");

  retryBtn.addEventListener("click", () => runRebuild(episodeId));
  if (rebuildBtn) {
    rebuildBtn.addEventListener("click", () => runRebuild(episodeId));
  }

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
      await pollUntilReady(episodeId);
      return;
    }

    if (shouldPrepare()) {
      await startProcessing(episodeId);
      await pollUntilReady(episodeId);
      return;
    }

    showPanel("processing");
    document.getElementById("processing-title").textContent = "Bu bölüm henüz hazır değil";
    document.getElementById("processing-message").textContent =
      "Altyazıyı oluşturmak için ana listeden Hazırla'ya tıklayın.";
  } catch (err) {
    titleEl.textContent = "Yükleme hatası";
    document.getElementById("error-message").textContent = String(err.message || err);
    showPanel("error");
  }
}

initWatchPage();
