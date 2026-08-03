from __future__ import annotations

from pathlib import Path
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine.android.android_bridge import AndroidBridge

app = FastAPI(title="AILM Android API")

bridge = AndroidBridge()

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}


class FilenameSearch(BaseModel):
    query: str


class SemanticSearch(BaseModel):
    query_vector: list[float]


class AdvancedSearchRequest(BaseModel):
    payload: dict[str, Any]


class ReviewUpdateRequest(BaseModel):
    item_id: str
    action: str
    payload: dict[str, Any] = {}


class ScanStartRequest(BaseModel):
    root: str


def _is_real_image(image) -> bool:
    path = str(getattr(image, "original_path", None) or getattr(image, "path", None) or "")
    if not path:
        return False

    lowered = path.lower().replace("/", "\\")
    if (
        "\\.git\\" in lowered
        or "\\.venv\\" in lowered
        or "\\node_modules\\" in lowered
        or "\\build\\" in lowered
        or "\\__pycache__\\" in lowered
    ):
        return False

    ext = str(getattr(image, "extension", None) or Path(path).suffix).lower()
    return ext in IMAGE_EXTENSIONS


@app.get("/health")
def health():
    return bridge.healthStatus()


@app.get("/statistics")
def statistics():
    return bridge.libraryStatistics()


@app.get("/collections")
def collections(query: str | None = None, page: int = 1, page_size: int = 50):
    return [_to_jsonable(item) for item in bridge.getCollections(query=query, page=page, page_size=page_size)]


@app.get("/images")
def images(query: str | None = None, page: int = 1, page_size: int = 200):
    return [_to_jsonable(item) for item in bridge.getLibraryImages(query=query, page=page, page_size=page_size)]


@app.get("/file")
def file(path: str):
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path))


@app.post("/scan/start")
def scan_start(request: ScanStartRequest):
    job = bridge.startScan(request.root)
    return _to_jsonable(job)


@app.get("/scan/status")
def scan_status():
    return _to_jsonable(bridge.scanStatus())


@app.post("/scan/pause")
def scan_pause():
    return {"ok": bridge.pauseScan()}


@app.post("/scan/resume")
def scan_resume():
    return {"ok": bridge.resumeScan()}


@app.post("/scan/cancel")
def scan_cancel():
    return {"ok": bridge.cancelScan()}


@app.get("/tags")
def tags():
    return bridge.getTags()


@app.post("/search/filename")
def search_filename(request: FilenameSearch):
    results = bridge.getLibraryImages(query=request.query, page=1, page_size=200)
    return {"results": [_to_jsonable(item) for item in results]}


@app.post("/search/semantic")
def search_semantic(request: SemanticSearch):
    results = bridge.semanticSearch(query_vector=request.query_vector)
    return {"results": [_to_jsonable(item) for item in results]}


@app.post("/search/advanced")
def search_advanced(request: AdvancedSearchRequest):
    return _to_jsonable(bridge.advancedSearch(payload=request.payload))


@app.get("/review/queue")
def review_queue():
    return _to_jsonable(bridge.getReviewQueue())


@app.post("/review/update")
def review_update(request: ReviewUpdateRequest):
    return {"updated": bridge.updateReview(request.item_id, request.action, request.payload)}


@app.get("/knowledge/packs")
def knowledge_packs():
    return _to_jsonable(bridge.listKnowledgePacks())


@app.get("/knowledge-packs")
def knowledge_packs_alias():
    return _to_jsonable(bridge.listKnowledgePacks())


@app.get("/downloads")
def downloads():
    return _to_jsonable(bridge.listDownloads())


@app.get("/plugins")
def plugins():
    return _to_jsonable(bridge.listPlugins())


def _to_jsonable(value: Any):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        data = dict(value.__dict__)
        data.pop("_sa_instance_state", None)
        return _to_jsonable(data)
    return value