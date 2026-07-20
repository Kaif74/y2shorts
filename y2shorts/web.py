"""FastAPI wrapper providing jobs, progress events, and local clip previews."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import run_pipeline
from .utils import PipelineError, extract_video_id

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web"


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Job:
    id: str
    url: str
    video_id: str
    status: Literal["queued", "running", "done", "error"] = "queued"
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    events: list[dict[str, object]] = field(default_factory=list)
    result: dict[str, object] | None = None
    error: str | None = None
    output_dir: Path | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def emit(self, stage: str, status: str, detail: str) -> None:
        event = {"stage": stage, "status": status, "detail": detail, "at": now()}
        with self.lock:
            self.events.append(event)
            self.updated_at = str(event["at"])

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {"id": self.id, "url": self.url, "video_id": self.video_id, "status": self.status,
                    "created_at": self.created_at, "updated_at": self.updated_at, "events": list(self.events),
                    "result": self.result, "error": self.error}


class CreateJobRequest(BaseModel):
    url: str


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
app = FastAPI(title="Shortform Studio", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def get_job(job_id: str) -> Job:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found in this server session.")
    return job


def build_result(job: Job, output_dir: Path) -> dict[str, object]:
    rankings_path = output_dir / "rankings.json"
    if not rankings_path.exists():
        return {"clips": [], "total_ranked": 0}
    rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
    clips: list[dict[str, object]] = []
    for index, candidate in enumerate(rankings.get("clips", []), start=1):
        rank, score = candidate.get("rank", index), round(float(candidate.get("score", 0)))
        filename = f"clip_{index:02d}_rank{rank}_score{score:02d}.mp4"
        if (output_dir / filename).is_file():
            clips.append({**candidate, "filename": filename, "video_url": f"/jobs/{job.id}/clips/{filename}"})
    return {"clips": clips, "total_ranked": len(rankings.get("clips", [])), "output_folder": str(output_dir)}


async def run_job(job: Job) -> None:
    job.status = "running"
    job.emit("fetch_transcript", "queued", "Job started")
    try:
        output_dir = await asyncio.to_thread(run_pipeline, job.url, on_progress=job.emit)
        job.output_dir, job.result, job.status = output_dir, build_result(job, output_dir), "done"
        job.emit("done", "done", f"{len(job.result['clips'])} video clip(s) ready to review")
    except Exception as exc:
        job.error = str(exc) if isinstance(exc, PipelineError) else f"Unexpected pipeline error: {exc}"
        job.status = "error"
        job.emit("error", "error", job.error)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/jobs", status_code=202)
async def create_job(request: CreateJobRequest) -> dict[str, object]:
    try:
        video_id = extract_video_id(request.url)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = Job(id=str(uuid.uuid4()), url=request.url.strip(), video_id=video_id)
    with JOBS_LOCK:
        JOBS[job.id] = job
    asyncio.create_task(run_job(job))
    return job.snapshot()


@app.get("/jobs")
async def list_jobs() -> dict[str, object]:
    with JOBS_LOCK:
        jobs = list(JOBS.values())
    return {"jobs": [job.snapshot() for job in sorted(jobs, key=lambda item: item.created_at, reverse=True)]}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, object]:
    return get_job(job_id).snapshot()


@app.websocket("/jobs/{job_id}/ws")
async def job_events(websocket: WebSocket, job_id: str, after: int = 0) -> None:
    try:
        job = get_job(job_id)
    except HTTPException:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    cursor = max(after, 0)
    try:
        while True:
            snapshot = job.snapshot()
            events = snapshot["events"]
            assert isinstance(events, list)
            for event in events[cursor:]:
                await websocket.send_json(event)
            cursor = len(events)
            if snapshot["status"] in {"done", "error"}:
                await websocket.send_json({"stage": "snapshot", "status": snapshot["status"], "job": snapshot})
                await websocket.close()
                return
            await asyncio.sleep(0.35)
    except WebSocketDisconnect:
        return


@app.get("/jobs/{job_id}/clips/{filename}")
async def serve_clip(job_id: str, filename: str, download: bool = False) -> FileResponse:
    job = get_job(job_id)
    if not job.output_dir:
        raise HTTPException(status_code=404, detail="No clips are ready for this job yet.")
    safe_name = Path(filename).name
    path = job.output_dir / safe_name
    if safe_name != filename or not path.is_file() or path.suffix.lower() != ".mp4":
        raise HTTPException(status_code=404, detail="Clip not found.")
    return FileResponse(path, media_type="video/mp4", filename=safe_name if download else None)
