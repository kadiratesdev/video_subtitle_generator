let episodes = [];
let pollTimer = null;
let catalogSettings = null;

const STATUS_LABELS = {
  ready: "Hazır",
  pending: "Bekliyor",
  processing: "İşleniyor",
  failed: "Başarısız",
};

const TAG_CLASSES = {
  ready: "inline-flex items-center gap-x-1.5 rounded-md bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-400 ring-1 ring-emerald-500/30",
  pending: "inline-flex items-center gap-x-1.5 rounded-md bg-neutral-800 px-2 py-1 text-[10px] font-medium text-neutral-400 ring-1 ring-neutral-700",
  processing: "inline-flex items-center gap-x-1.5 rounded-md bg-sky-500/10 px-2 py-1 text-[10px] font-medium text-sky-400 ring-1 ring-sky-500/30",
  failed: "inline-flex items-center gap-x-1.5 rounded-md bg-red-500/10 px-2 py-1 text-[10px] font-medium text-red-400 ring-1 ring-red-500/30",
};

const CHIP_ACTIVE =
  "filter-chip rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 font-mono text-[11px] text-emerald-400 uppercase";
const CHIP_IDLE =
  "filter-chip rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-1.5 font-mono text-[11px] text-neutral-500 uppercase hover:border-neutral-700 hover:text-neutral-300";

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

function setActiveFilter(value) {
  document.getElementById("filter-status").value = value;
  document.querySelectorAll("#filter-bar .filter-chip").forEach((chip) => {
    chip.className = chip.dataset.filter === value ? CHIP_ACTIVE : CHIP_IDLE;
  });
}

function closeSettingsDrawer() {
  const HSOverlay = window.HSOverlay;
  if (!HSOverlay) return;
  const inst = HSOverlay.getInstance("#hs-settings-drawer", true);
  inst?.element?.close();
}

function closeApiModal() {
  const HSOverlay = window.HSOverlay;
  if (!HSOverlay) return;
  const inst = HSOverlay.getInstance("#hs-api-modal", true);
  inst?.element?.close();
}

const GROQ_BADGE_OK =
  "inline-flex shrink-0 items-center rounded-md bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] font-medium text-emerald-400 ring-1 ring-emerald-500/30";
const GROQ_BADGE_MISSING =
  "inline-flex shrink-0 items-center rounded-md bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] font-medium text-amber-400 ring-1 ring-amber-500/30";

function groqKeyFields(scope) {
  if (scope === "drawer") {
    return {
      input: document.getElementById("groq-api-drawer-input"),
      errEl: document.getElementById("groq-api-drawer-error"),
      okEl: document.getElementById("groq-api-drawer-success"),
      btn: document.getElementById("save-groq-key-drawer-btn"),
    };
  }
  return {
    input: document.getElementById("groq-api-input"),
    errEl: document.getElementById("groq-api-error"),
    okEl: document.getElementById("groq-api-success"),
    btn: document.getElementById("save-groq-key-btn"),
  };
}

function syncGroqKeyStatus(hasGroqKey) {
  const statusEl = document.getElementById("groq-api-drawer-status");
  if (!statusEl) return;
  if (hasGroqKey) {
    statusEl.textContent = "Tanımlı";
    statusEl.className = GROQ_BADGE_OK;
  } else {
    statusEl.textContent = "Eksik";
    statusEl.className = GROQ_BADGE_MISSING;
  }
}

async function saveGroqApiKey(scope = "modal") {
  const { input, errEl, okEl, btn } = groqKeyFields(scope);
  const key = input.value.trim();

  errEl.hidden = true;
  okEl.hidden = true;
  errEl.textContent = "";
  if (okEl.tagName === "DIV") {
    okEl.textContent = "Anahtar kaydedildi — çeviri başlatabilirsiniz.";
  }

  if (!key) {
    errEl.textContent = "API anahtarı boş olamaz.";
    errEl.hidden = false;
    return;
  }

  btn.disabled = true;
  try {
    const res = await fetch("/api/settings/groq-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKey: key }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Anahtar kaydedilemedi");
    }
    input.value = "";
    okEl.hidden = false;
    document.getElementById("api-warning").hidden = true;
    syncGroqKeyStatus(true);
    if (scope === "modal") {
      setTimeout(() => {
        closeApiModal();
        okEl.hidden = true;
      }, 900);
    } else {
      setTimeout(() => {
        okEl.hidden = true;
      }, 2000);
    }
    await loadData();
  } catch (err) {
    errEl.textContent = String(err.message || err);
    errEl.hidden = false;
  } finally {
    btn.disabled = false;
  }
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
    listEl.innerHTML = `
      <div class="flex flex-col items-center justify-center rounded-xl border border-dashed border-neutral-800 bg-neutral-900/40 px-6 py-16 text-center">
        <p class="font-mono text-[10px] tracking-widest text-neutral-600 uppercase">boş</p>
        <p class="mt-2 text-sm text-neutral-500">${escapeHtml(emptyMsg)}</p>
      </div>`;
    return;
  }

  listEl.innerHTML = items
    .map((ep) => {
      const status = ep.status || "pending";
      const progress = Math.round((ep.progress || 0) * 100);
      const canWatch = status === "ready" || ep.hasSubtitles;
      const isProcessing = status === "processing";
      const actionLabel = canWatch ? "İzle" : isProcessing ? "…" : "Hazırla";
      const href = canWatch
        ? `/watch/${encodeURIComponent(ep.id)}`
        : `/watch/${encodeURIComponent(ep.id)}?prepare=1`;
      const tagClass = TAG_CLASSES[status] || TAG_CLASSES.pending;
      const subtitle = isProcessing
        ? escapeHtml(ep.progressMessage || "İşlem devam ediyor…")
        : ep.error
          ? escapeHtml(ep.error)
          : canWatch
            ? "Türkçe altyazı hazır"
            : "Henüz işlenmedi";

      return `
        <article class="flex flex-col gap-4 rounded-xl border border-neutral-800 bg-neutral-900/60 p-4 transition hover:border-emerald-500/25 sm:flex-row sm:items-center sm:justify-between" data-id="${escapeHtml(ep.id)}">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="truncate text-sm font-semibold text-neutral-100">${escapeHtml(ep.title)}</h2>
              <span class="${tagClass}">${escapeHtml(STATUS_LABELS[status] || status)}</span>
            </div>
            <p class="mt-1 truncate font-mono text-[11px] text-neutral-500">${escapeHtml(ep.videoName || "")}</p>
            <p class="mt-1 text-xs ${ep.error ? "text-red-400" : "text-neutral-500"}">${subtitle}</p>
            ${
              isProcessing
                ? `<div class="mt-2 h-1.5 max-w-xs overflow-hidden rounded-full bg-neutral-800"><div class="h-full rounded-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)] transition-[width]" style="width:${progress}%"></div></div>`
                : ""
            }
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <a class="inline-flex items-center justify-center gap-x-2 rounded-lg px-3.5 py-2 text-xs font-semibold no-underline ${canWatch ? "bg-emerald-500 text-neutral-950 hover:bg-emerald-400" : "border border-neutral-700 bg-neutral-950 text-neutral-300 hover:border-neutral-600"} ${isProcessing ? "pointer-events-none opacity-40" : ""}" href="${href}">${actionLabel}</a>
            ${
              canWatch || status === "failed" || status === "ready"
                ? `<button type="button" class="rebuild-btn inline-flex size-9 items-center justify-center rounded-lg border border-neutral-800 text-neutral-400 hover:border-neutral-700 hover:text-emerald-400" data-id="${escapeHtml(ep.id)}" title="Yeniden oluştur">↺</button>`
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

  modeEl.value = settings.mode || "local";
  remoteUrlEl.value = settings.remoteUrl || "";
  localPathEl.value = settings.localPath || "";
  langEl.value = settings.sourceLang || "es";

  const isLocal = modeEl.value === "local";
  remoteFields.hidden = isLocal;
  localFields.hidden = !isLocal;

  if (isLocal) {
    hint.textContent = settings.localPathExists
      ? `Aktif: ${settings.localPath}`
      : "Geçerli bir klasör yolu girin veya seçin.";
  } else {
    hint.textContent = settings.remoteUrl
      ? `Uzak: ${settings.remoteUrl}`
      : "Uzak sunucu adresi girin.";
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

    document.getElementById("api-warning").hidden = !!statusData.hasGroqKey;
    syncGroqKeyStatus(!!statusData.hasGroqKey);
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
    document.getElementById("episode-list").innerHTML = `
      <div class="rounded-xl border border-red-500/30 bg-red-500/5 px-6 py-12 text-center text-sm text-red-400">
        Liste yüklenemedi: ${escapeHtml(String(err))}
      </div>`;
  }
}

document.getElementById("search").addEventListener("input", renderEpisodes);

document.getElementById("filter-bar").addEventListener("click", (e) => {
  const chip = e.target.closest(".filter-chip");
  if (!chip) return;
  setActiveFilter(chip.dataset.filter || "all");
  renderEpisodes();
});

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
    closeSettingsDrawer();
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

document.getElementById("save-groq-key-btn").addEventListener("click", () => saveGroqApiKey("modal"));
document.getElementById("groq-api-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") saveGroqApiKey("modal");
});

document.getElementById("save-groq-key-drawer-btn").addEventListener("click", () => saveGroqApiKey("drawer"));
document.getElementById("groq-api-drawer-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") saveGroqApiKey("drawer");
});

document.getElementById("toggle-groq-key-visibility")?.addEventListener("click", () => {
  const input = document.getElementById("groq-api-drawer-input");
  const btn = document.getElementById("toggle-groq-key-visibility");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.querySelector(".icon-eye")?.classList.toggle("hidden", show);
  btn.querySelector(".icon-eye-off")?.classList.toggle("hidden", !show);
  btn.setAttribute("aria-label", show ? "Anahtarı gizle" : "Anahtarı göster");
});

loadData();
setInterval(loadData, 8000);
