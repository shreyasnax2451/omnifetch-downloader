import os
import re
import time
import uuid
import shutil
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="Video Downloader (YouTube & X)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"An unexpected error occurred: {str(exc)}"}
    )

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# In-memory job tracker
jobs: Dict[str, Dict[str, Any]] = {}

class VideoInfoRequest(BaseModel):
    url: str

class VideoDownloadRequest(BaseModel):
    url: str
    format_type: str = "best"  # "best", "1080p", "720p", "480p", "mp3"


def format_duration(seconds: Any) -> str:
    if seconds is None:
        return "--:--"
    try:
        total_sec = int(round(float(seconds)))
        m, s = divmod(total_sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except Exception:
        return "--:--"


def detect_platform(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "twitter.com" in u or "x.com" in u:
        return "X (Twitter)"
    return "Web Video"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def cleanup_old_files():
    now = time.time()
    for item in DOWNLOADS_DIR.iterdir():
        if item.is_file():
            # Remove files older than 45 minutes
            if now - item.stat().st_mtime > 45 * 60:
                try:
                    item.unlink()
                except Exception:
                    pass


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = BASE_DIR / "templates" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Index template not found")
    return index_path.read_text(encoding="utf-8")


@app.post("/api/info")
async def get_video_info(payload: VideoInfoRequest):
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Please enter a valid video link.")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"]
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
        }
    }

    try:
        info = await asyncio.to_thread(_extract_info, url, ydl_opts)
    except Exception as e:
        error_msg = str(e)
        if "Sign in to confirm" in error_msg:
            error_msg = "This video requires login / bot verification."
        elif "Private video" in error_msg:
            error_msg = "This video is private or unavailable."
        elif "Unable to extract" in error_msg:
            error_msg = "Could not extract video. Please ensure the link is a valid public video."
        raise HTTPException(status_code=400, detail=error_msg)

    title = info.get("title", "Untitled Video")
    thumbnail = info.get("thumbnail") or ""
    duration = info.get("duration")
    uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "Unknown Author"
    platform = detect_platform(url)

    # Inspect available resolutions
    available_heights = set()
    formats = info.get("formats", [])
    has_audio = False
    for f in formats:
        h = f.get("height")
        if h:
            available_heights.add(h)
        if f.get("acodec") and f.get("acodec") != "none":
            has_audio = True

    # Pre-select available format presets
    preset_formats = []
    if any(h >= 1080 for h in available_heights):
        preset_formats.append({"id": "1080p", "label": "Full HD (1080p MP4)", "badge": "1080p"})
    if any(h >= 720 for h in available_heights):
        preset_formats.append({"id": "720p", "label": "HD (720p MP4)", "badge": "720p"})
    if any(h >= 480 for h in available_heights):
        preset_formats.append({"id": "480p", "label": "Standard (480p MP4)", "badge": "480p"})
    
    # Always include Best Video & MP3
    preset_formats.insert(0, {"id": "best", "label": "Best Available Quality (MP4)", "badge": "Best"})
    preset_formats.append({"id": "mp3", "label": "Audio Only (MP3 192kbps)", "badge": "Audio"})

    return {
        "title": title,
        "thumbnail": thumbnail,
        "duration_str": format_duration(duration),
        "duration": duration,
        "uploader": uploader,
        "platform": platform,
        "webpage_url": info.get("webpage_url", url),
        "formats": preset_formats,
    }


def _extract_info(url: str, opts: dict):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _download_task(job_id: str, url: str, format_type: str):
    job = jobs[job_id]
    job["status"] = "downloading"
    job["progress"] = 0
    job["speed"] = ""
    job["eta"] = ""

    def progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                percent = round((downloaded / total) * 100, 1)
                job["progress"] = percent
            else:
                job["progress"] = 50
            
            # Speed
            speed = d.get("speed")
            if speed:
                job["speed"] = f"{speed / (1024 * 1024):.1f} MB/s"
            
            # ETA
            eta = d.get("eta")
            if eta:
                job["eta"] = f"{eta}s"
            
        elif d.get("status") == "finished":
            job["status"] = "processing"
            job["progress"] = 99

    out_id = str(uuid.uuid4())[:8]
    out_template = str(DOWNLOADS_DIR / f"{out_id}_%(title).100B.%(ext)s")

    ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

    ydl_opts: Dict[str, Any] = {
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        "socket_timeout": 30,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"]
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
        }
    }

    if os.path.exists(ffmpeg_bin):
        ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_bin)

    if format_type == "mp3":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    elif format_type == "1080p":
        ydl_opts["format"] = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"
        ydl_opts["merge_output_format"] = "mp4"
    elif format_type == "720p":
        ydl_opts["format"] = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best"
        ydl_opts["merge_output_format"] = "mp4"
    elif format_type == "480p":
        ydl_opts["format"] = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best"
        ydl_opts["merge_output_format"] = "mp4"
    else:  # "best"
        ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(url, download=True)
            # Find the saved file
            if "requested_downloads" in res and res["requested_downloads"]:
                downloaded_file = res["requested_downloads"][0]["filepath"]
            else:
                downloaded_file = ydl.prepare_filename(res)
                if format_type == "mp3":
                    downloaded_file = os.path.splitext(downloaded_file)[0] + ".mp3"

            file_path = Path(downloaded_file)
            if not file_path.exists():
                # Search directory for file with matching prefix
                matched = list(DOWNLOADS_DIR.glob(f"{out_id}_*"))
                if matched:
                    file_path = matched[0]
                else:
                    raise FileNotFoundError("Downloaded output file was not found.")

            clean_name = file_path.name
            # remove out_id prefix from downloaded file name for user download
            if clean_name.startswith(f"{out_id}_"):
                clean_name = clean_name[len(out_id) + 1 :]

            job["status"] = "completed"
            job["progress"] = 100
            job["file_path"] = str(file_path)
            job["download_name"] = clean_name
            job["file_size_mb"] = round(file_path.stat().st_size / (1024 * 1024), 2)

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)


@app.post("/api/download")
async def start_download(payload: VideoDownloadRequest, background_tasks: BackgroundTasks):
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Invalid URL")

    # Clean old temp files in background
    background_tasks.add_task(cleanup_old_files)

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "format": payload.format_type,
        "status": "queued",
        "progress": 0,
        "created_at": time.time(),
        "speed": "",
        "eta": "",
    }

    # Start download task in background thread
    asyncio.create_task(asyncio.to_thread(_download_task, job_id, url, payload.format_type))

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress", 0),
        "speed": job.get("speed", ""),
        "eta": job.get("eta", ""),
        "download_name": job.get("download_name", ""),
        "file_size_mb": job.get("file_size_mb", 0),
        "error": job.get("error", ""),
    }


@app.api_route("/api/file/{job_id}", methods=["GET", "HEAD"])
async def get_downloaded_file(job_id: str):
    job = jobs.get(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="File is not ready or does not exist")

    file_path = Path(job["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    filename = job.get("download_name", file_path.name)
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )
