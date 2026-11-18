from __future__ import annotations

import base64
import io
import os
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from paddleocr import PaddleOCR

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

app = FastAPI(title="MedVision OCR Lab")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)


@lru_cache(maxsize=1)
def get_ocr() -> PaddleOCR:
    return PaddleOCR(
        lang="korean",
        ocr_version="PP-OCRv5",
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def decode_image(content: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, "JPG, PNG 또는 WEBP 이미지를 올려 주세요.")
    return image


def resize_for_ocr(image: np.ndarray, max_side: int = 1800, min_side: int = 900) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    scale = min(1.0, max_side / longest)
    if longest < min_side:
        scale = min_side / longest
    if abs(scale - 1.0) < 0.01:
        return image
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)


def variants(image: np.ndarray) -> dict[str, np.ndarray]:
    base = resize_for_ocr(image)
    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    blur = cv2.GaussianBlur(base, (0, 0), 2)
    return {
        "original": base,
        "gray": gray,
        "clahe": cv2.createCLAHE(2.0, (8, 8)).apply(gray),
        "otsu": cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        "adaptive": cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11),
        "sharpen": cv2.addWeighted(base, 1.7, blur, -0.7, 0),
    }


def as_data_url(image: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 86])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode()


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text).lower())


def cer(reference: str, prediction: str) -> float | None:
    ref = normalized(reference)
    return None if not ref else levenshtein(ref, normalized(prediction)) / len(ref)


def extract_fields(text: str) -> dict[str, list[str]]:
    doses = re.findall(r"\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|μg|㎍|ml|mL|밀리그람|그램|정|캡슐)\b", text, re.I)
    makers = re.findall(r"[가-힣A-Za-z0-9㈜()·&\- ]{2,25}(?:제약|약품|바이오|Pharma|Inc\.?|Co\.?\s*,?\s*Ltd\.?)", text, re.I)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name_candidates = [x for x in lines if 2 <= len(x) <= 25 and not re.fullmatch(r"[\d\W]+", x)][:5]
    return {
        "medicine_names": name_candidates,
        "doses": list(dict.fromkeys(doses)),
        "manufacturers": list(dict.fromkeys(x.strip() for x in makers)),
    }


def analyze_one(ocr: PaddleOCR, name: str, image: np.ndarray, reference: str) -> dict:
    started = time.perf_counter()
    predictions = list(ocr.predict(image))
    elapsed = time.perf_counter() - started
    if predictions:
        raw = predictions[0].json
        data = raw.get("res", raw)
        texts = [str(x) for x in data.get("rec_texts", [])]
        scores = [float(x) for x in data.get("rec_scores", [])]
        boxes = data.get("rec_boxes", [])
    else:
        texts, scores, boxes = [], [], []

    items = []
    for index, text in enumerate(texts):
        box = boxes[index] if index < len(boxes) else [0, index * 20, 0, index * 20]
        items.append({
            "text": text,
            "score": round(scores[index], 4) if index < len(scores) else 0,
            "x": int(box[0]),
            "y": int(box[1]),
        })
    items.sort(key=lambda x: (x["y"] // 18, x["x"]))
    text = "\n".join(x["text"] for x in items)
    error = cer(reference, text)
    return {
        "variant": name,
        "text": text,
        "items": items,
        "fields": extract_fields(text),
        "count": len(texts),
        "confidence": round(sum(scores) / len(scores), 4) if scores else 0,
        "cer": round(error, 4) if error is not None else None,
        "seconds": round(elapsed, 2),
        "preview": as_data_url(image),
    }


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "model": "PaddleOCR PP-OCRv5 Korean", "device": "CPU"}


def run_job(job_id: str, content: bytes, filename: str, ground_truth: str, selected_variants: str) -> None:
    try:
        source = decode_image(content)
        prepared = variants(source)
        requested = [x for x in selected_variants.split(",") if x in prepared] or ["original"]
        ocr = get_ocr()
        results = []
        for index, name in enumerate(requested):
            with JOBS_LOCK:
                JOBS[job_id].update({"status": "processing", "current": name, "progress": int(index / len(requested) * 100)})
            results.append(analyze_one(ocr, name, prepared[name], ground_truth.strip()))
        results.sort(key=lambda x: x["cer"] if x["cer"] is not None else -x["confidence"])
        payload = {
            "filename": filename,
            "original_size": {"width": int(source.shape[1]), "height": int(source.shape[0])},
            "processed_size": {"width": int(prepared["original"].shape[1]), "height": int(prepared["original"].shape[0])},
            "results": results,
        }
        with JOBS_LOCK:
            JOBS[job_id].update({"status": "complete", "progress": 100, "result": payload})
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id].update({"status": "failed", "error": str(exc)[:500]})


@app.post("/api/jobs", status_code=202)
async def create_job(
    image: UploadFile = File(...),
    ground_truth: str = Form(""),
    selected_variants: str = Form("original"),
) -> dict:
    content = await image.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "이미지는 20MB 이하로 올려 주세요.")
    decode_image(content)
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "progress": 0, "created_at": time.time()}
        expired = [key for key, value in JOBS.items() if time.time() - value.get("created_at", 0) > 3600]
        for key in expired:
            JOBS.pop(key, None)
    EXECUTOR.submit(run_job, job_id, content, image.filename or "upload", ground_truth, selected_variants)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "작업을 찾을 수 없습니다. 다시 분석해 주세요.")
        return dict(job)

