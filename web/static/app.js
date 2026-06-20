let episodes = [];
let pollTimer = null;
let catalogSettings = null;

const STATUS_LABELS = {
  ready: "Hazır",
  pending: "Bekliyor",
  processing: "İşleniyor",
  failed: "Başarısız",
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function getFilters() {
  return {
    query: document.getElementById("search").value.trim().toLowerCase(),
    status: document.getElementById("filter-status").value,
  };
}

function filteredEpisodes() {
  const { query, status } = getFilters();
  return episodes.filter((ep) => {
    const matchesQuery =
      !query ||
      ep.title.toLowerCase().includes(query) ||
      ep.id.toLowerCase().includes(query) ||
      String(ep.videoName || "").toLowerCase().includes(query);
    const matchesStatus = status === "all" || ep.status === status;
    return matchesQuery && matchesStatus;
  });
}

function renderEpisodes() {
  const listEl = document.getElementById("episode-list");
  const items = filteredEpisodes();

  if (!items.length) {
    const emptyMsg =
      catalogSettings?.mode === "local" && !catalogSettings?.localPathExists
        ? "Yerel klasör seçin veya klasörde video yok."
        : "Eşleşen video bulunamadı.";
    listEl.innerHTML = `<p class="empty-state">${escapeHtml(emptyMsg)}</p>`;
    return;
  }

  listEl.innerHTML = items
    .map((ep) => {
      const status = ep.status || "pending";
      const progress = Math.round((ep.progress || 0) * 100);
      const canWatch = status === "ready" || ep.hasSubtitles;
      const isProcessing = status === "processing";
      const actionLabel = canWatch ? "İzle" : isProcessing ? "İşleniyor" : "Hazırla";
      const actionClass = canWatch ? "primary" : "secondary";
      const href = canWatch
        ? `/watch/${encodeURIComponent(ep.id)}`
        : `/watch/${encodeURIComponent(ep.id)}?prepare=1`;

      return `
        <article class="episode-card" data-id="${escapeHtml(ep.id)}">
          <div class="episode-top">
            <div>
              <h2>${escapeHtml(ep.title)}</h2>
              <p>${escapeHtml(ep.videoName || "")}</p>
            </div>
            <span class="badge ${escapeHtml(status)}">${escapeHtml(STATUS_LABELS[status] || status)}</span>
          </div>
          ${
            isProcessing
              ? `<div class="progress-mini" aria-hidden="true"><span style="width:${progress}%"></span></div>
                 <p>${escapeHtml(ep.progressMessage || "İşleniyor...")}</p>`
              : ep.error
                ? `<p>${escapeHtml(ep.error)}</p>`
                : `<p>${canWatch ? "Türkçe altyazı hazır" : "Henüz çevrilmedi"}</p>`
          }
          <div class="card-actions">
            <a class="btn ${actionClass}" href="${href}">${actionLabel}</a>
            ${
              canWatch || status === "failed" || status === "ready"
                ? `<button type="button" class="btn ghost rebuild-btn" data-id="${escapeHtml(ep.id)}">Yeniden oluştur</button>`
                : ""
            }
          </div>
        </article>`;
    })
    .join("");
}

function syncSourceForm(settings) {
  if (!settings) return;
  catalogSettings = settings;

  const modeEl = document.getElementById("source-mode");
  const remoteUrlEl = document.getElementById("remote-url");
  const localPathEl = document.getElementById("local-path");
  const langEl = document.getElementById("source-lang");
  const remoteFields = document.getElementById("remote-fields");
  const localFields = document.getElementById("local-fields");
  const hint = document.getElementById("source-hint");

  modeEl.value = settings.mode || "remote";
  remoteUrlEl.value = settings.remoteUrl || "";
  localPathEl.value = settings.localPath || "";
  langEl.value = settings.sourceLang || "es";

  const isLocal = modeEl.value === "local";
  remoteFields.hidden = isLocal;
  localFields.hidden = !isLocal;

  if (isLocal) {
    hint.textContent = settings.localPathExists
      ? `Yerel klasör: ${settings.localPath}`
      : "Geçerli bir klasör yolu girin veya seçin.";
  } else {
    hint.textContent = `Uzak kaynak: ${settings.remoteUrl}`;
  }
}

async function applySourceSettings(body) {
  const res = await fetch("/api/catalog/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Kaynak güncellenemedi");
  }
  const data = await res.json();
  syncSourceForm(data.settings);
  await loadData();
}

async function rebuildEpisode(episodeId, { keepVideo = false } = {}) {
  const msg = keepVideo
    ? "Altyazılar silinip yeniden oluşturulacak (video dosyası korunur)."
    : "Tüm çıktılar silinip baştan oluşturulacak.";
  if (!window.confirm(`${msg}\n\nDevam edilsin mi?`)) {
    return;
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

async function loadData() {
  try {
    const [episodesRes, statusRes] = await Promise.all([
      fetch("/api/episodes"),
      fetch("/api/status"),
    ]);
    const episodesData = await episodesRes.json();
    const statusData = await statusRes.json();

    episodes = episodesData.episodes || [];
    document.getElementById("stat-total").textContent = statusData.total ?? "0";
    document.getElementById("stat-ready").textContent = statusData.ready ?? "0";
    document.getElementById("stat-pending").textContent = statusData.pending ?? "0";

    const warning = document.getElementById("api-warning");
    warning.hidden = !!statusData.hasGroqKey;

    syncSourceForm(statusData.catalog);

    const currentJob = document.getElementById("current-job");
    const currentJobName = document.getElementById("current-job-name");
    if (statusData.busy && statusData.currentJob) {
      currentJob.hidden = false;
      currentJobName.textContent = statusData.currentJob;
    } else {
      currentJob.hidden = true;
    }

    renderEpisodes();

    if (statusData.busy && !pollTimer) {
      pollTimer = setInterval(loadData, 2500);
    } else if (!statusData.busy && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  } catch (err) {
    document.getElementById("episode-list").innerHTML =
      `<p class="empty-state">Liste yüklenemedi: ${escapeHtml(String(err))}</p>`;
  }
}

document.getElementById("search").addEventListener("input", renderEpisodes);
document.getElementById("filter-status").addEventListener("change", renderEpisodes);
document.getElementById("refresh-btn").addEventListener("click", loadData);

document.getElementById("episode-list").addEventListener("click", async (e) => {
  const btn = e.target.closest(".rebuild-btn");
  if (!btn) return;
  btn.disabled = true;
  try {
    await rebuildEpisode(btn.dataset.id, { keepVideo: false });
    await loadData();
  } catch (err) {
    alert(String(err.message || err));
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("source-mode").addEventListener("change", (e) => {
  const isLocal = e.target.value === "local";
  document.getElementById("remote-fields").hidden = isLocal;
  document.getElementById("local-fields").hidden = !isLocal;
});

document.getElementById("apply-source-btn").addEventListener("click", async () => {
  const btn = document.getElementById("apply-source-btn");
  btn.disabled = true;
  try {
    await applySourceSettings({
      mode: document.getElementById("source-mode").value,
      remoteUrl: document.getElementById("remote-url").value.trim(),
      localPath: document.getElementById("local-path").value.trim(),
      sourceLang: document.getElementById("source-lang").value,
    });
  } catch (err) {
    document.getElementById("source-hint").textContent = String(err.message || err);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("pick-folder-btn").addEventListener("click", async () => {
  const btn = document.getElementById("pick-folder-btn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/catalog/pick-folder", { method: "POST" });
    const data = await res.json();
    if (!data.ok) {
      document.getElementById("source-hint").textContent = data.error || "Klasör seçilmedi";
      return;
    }
    syncSourceForm(data.settings);
    await loadData();
  } catch (err) {
    document.getElementById("source-hint").textContent = String(err.message || err);
  } finally {
    btn.disabled = false;
  }
});

loadData();
setInterval(loadData, 8000);
