let currentVideoData = null;
let selectedFormat = "best";
let activeJobId = null;
let pollInterval = null;

const urlInput = document.getElementById("video-url-input");
const pasteBtn = document.getElementById("paste-btn");
const clearBtn = document.getElementById("clear-btn");
const submitBtn = document.getElementById("submit-btn");
const btnText = submitBtn.querySelector(".btn-text");
const btnSpinner = submitBtn.querySelector(".btn-spinner");
const btnIcon = submitBtn.querySelector(".btn-icon");

const previewSection = document.getElementById("preview-section");
const videoThumbnail = document.getElementById("video-thumbnail");
const videoDuration = document.getElementById("video-duration");
const previewPlatformBadge = document.getElementById("preview-platform-badge");
const videoTitle = document.getElementById("video-title");
const videoUploader = document.getElementById("video-uploader");
const formatsGrid = document.getElementById("formats-grid");

const downloadTriggerBtn = document.getElementById("download-trigger-btn");
const downloadBtnText = document.getElementById("download-btn-text");
const progressPanel = document.getElementById("progress-panel");
const progressStatusText = document.getElementById("progress-status-text");
const progressPercent = document.getElementById("progress-percent");
const progressSpeed = document.getElementById("progress-speed");
const progressBarFill = document.getElementById("progress-bar-fill");

const successCard = document.getElementById("download-success-card");
const successFilename = document.getElementById("success-filename");
const saveFileLink = document.getElementById("save-file-link");

const errorBanner = document.getElementById("error-banner");
const errorMessage = document.getElementById("error-message");

// Input listeners
urlInput.addEventListener("input", () => {
  if (urlInput.value.trim().length > 0) {
    pasteBtn.classList.add("hidden");
    clearBtn.classList.remove("hidden");
  } else {
    pasteBtn.classList.remove("hidden");
    clearBtn.classList.add("hidden");
  }
});

clearBtn.addEventListener("click", () => {
  urlInput.value = "";
  urlInput.focus();
  pasteBtn.classList.remove("hidden");
  clearBtn.classList.add("hidden");
  hidePreview();
  hideError();
  hideSuccess();
});

pasteBtn.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      urlInput.value = text.trim();
      pasteBtn.classList.add("hidden");
      clearBtn.classList.remove("hidden");
      handleFetchInfo();
    }
  } catch (err) {
    urlInput.focus();
  }
});

function showError(msg) {
  errorMessage.textContent = msg;
  errorBanner.classList.remove("hidden");
  errorBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideError() {
  errorBanner.classList.add("hidden");
}

function hideSuccess() {
  successCard.classList.add("hidden");
}

function hidePreview() {
  previewSection.classList.add("hidden");
  progressPanel.classList.add("hidden");
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

function setAnalyzingState(loading) {
  submitBtn.disabled = loading;
  if (loading) {
    btnText.textContent = "Analyzing...";
    btnSpinner.classList.remove("hidden");
    btnIcon.classList.add("hidden");
  } else {
    btnText.textContent = "Analyze Link";
    btnSpinner.classList.add("hidden");
    btnIcon.classList.remove("hidden");
  }
}

async function handleFetchInfo() {
  const url = urlInput.value.trim();
  if (!url) {
    showError("Please paste a valid YouTube or X (Twitter) video link.");
    return;
  }

  hideError();
  hideSuccess();
  hidePreview();
  setAnalyzingState(true);

  try {
    const response = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    let data;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const rawText = await response.text();
      data = { detail: rawText || "Server returned an unexpected response." };
    }

    if (!response.ok) {
      throw new Error(data.detail || `Server error (${response.status})`);
    }

    currentVideoData = data;
    renderPreview(data);
  } catch (err) {
    showError(err.message || "Failed to analyze video URL.");
  } finally {
    setAnalyzingState(false);
  }
}

function renderPreview(data) {
  videoTitle.textContent = data.title;
  videoUploader.textContent = data.uploader;
  videoDuration.textContent = data.duration_str;
  videoThumbnail.src = data.thumbnail || "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80";
  previewPlatformBadge.textContent = data.platform;

  if (data.platform.includes("X") || data.platform.includes("Twitter")) {
    previewPlatformBadge.style.background = "#0f172a";
    previewPlatformBadge.style.border = "1px solid rgba(255,255,255,0.2)";
  } else {
    previewPlatformBadge.style.background = "#e11d48";
    previewPlatformBadge.style.border = "none";
  }

  // Populate format cards
  formatsGrid.innerHTML = "";
  selectedFormat = data.formats[0]?.id || "best";

  data.formats.forEach((fmt, index) => {
    const card = document.createElement("div");
    card.className = `format-card ${index === 0 ? "selected" : ""}`;
    card.innerHTML = `
      <span class="format-title">${fmt.label}</span>
      <span class="format-badge">${fmt.badge}</span>
    `;

    card.addEventListener("click", () => {
      document.querySelectorAll(".format-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
      selectedFormat = fmt.id;
    });

    formatsGrid.appendChild(card);
  });

  // Reset download button
  downloadTriggerBtn.disabled = false;
  downloadBtnText.textContent = "Download Now";
  progressPanel.classList.add("hidden");

  previewSection.classList.remove("hidden");
  previewSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function startDownloadProcess() {
  if (!currentVideoData) return;

  hideError();
  hideSuccess();

  downloadTriggerBtn.disabled = true;
  downloadBtnText.textContent = "Preparing Download...";
  progressPanel.classList.remove("hidden");
  progressBarFill.style.width = "5%";
  progressPercent.textContent = "5%";
  progressStatusText.textContent = "Connecting to video stream...";
  progressSpeed.textContent = "-- MB/s";

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentVideoData.webpage_url,
        format_type: selectedFormat,
      }),
    });

    let data;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const rawText = await response.text();
      data = { detail: rawText || "Failed to start download job." };
    }

    if (!response.ok) {
      throw new Error(data.detail || "Failed to start download job.");
    }

    activeJobId = data.job_id;
    pollDownloadStatus(activeJobId);
  } catch (err) {
    showError(err.message || "Failed to start download.");
    downloadTriggerBtn.disabled = false;
    downloadBtnText.textContent = "Download Now";
    progressPanel.classList.add("hidden");
  }
}

function pollDownloadStatus(jobId) {
  if (pollInterval) clearInterval(pollInterval);

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      if (!res.ok) return;

      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) return;

      const statusData = await res.json();

      if (statusData.status === "downloading") {
        const progress = Math.max(statusData.progress || 10, 8);
        progressBarFill.style.width = `${progress}%`;
        progressPercent.textContent = `${Math.round(progress)}%`;
        progressStatusText.textContent = "Downloading video stream...";
        if (statusData.speed) {
          progressSpeed.textContent = statusData.speed;
        }
      } else if (statusData.status === "processing") {
        progressBarFill.style.width = "95%";
        progressPercent.textContent = "95%";
        progressStatusText.textContent = "Merging streams & processing audio/video...";
      } else if (statusData.status === "completed") {
        clearInterval(pollInterval);
        progressBarFill.style.width = "100%";
        progressPercent.textContent = "100%";
        progressStatusText.textContent = "Download complete!";

        // Show ready banner
        const fileUrl = `/api/file/${jobId}`;
        const filename = statusData.download_name || "downloaded_video.mp4";
        successFilename.textContent = `${filename} (${statusData.file_size_mb} MB)`;
        saveFileLink.href = fileUrl;
        saveFileLink.setAttribute("download", filename);
        successCard.classList.remove("hidden");

        // Automatically trigger browser native download
        triggerBrowserDownload(fileUrl, filename);

        // Reset button
        downloadTriggerBtn.disabled = false;
        downloadBtnText.textContent = "Download Again";
      } else if (statusData.status === "failed") {
        clearInterval(pollInterval);
        progressPanel.classList.add("hidden");
        downloadTriggerBtn.disabled = false;
        downloadBtnText.textContent = "Download Now";
        showError(statusData.error || "An error occurred during download.");
      }
    } catch (e) {
      console.warn("Polling error:", e);
    }
  }, 750);
}

function triggerBrowserDownload(url, filename) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
