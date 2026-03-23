from __future__ import annotations

import base64
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.config import settings
from speech_services.core.transcriber import CodeWhisper


SERVICE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SERVICE_ROOT.parent
AUDIO_STORAGE_DIR = SERVICE_ROOT / "audio"
AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_MODELS = {"tiny", "base", "small", "medium", "large"}
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
GPU_AVAILABLE = torch.cuda.is_available()
whisper_instances: dict[str, CodeWhisper] = {}

router = APIRouter(tags=["speech"])


def get_whisper_instance(model_name: str | None = None) -> CodeWhisper:
    selected_model = model_name or settings.SPEECH_DEFAULT_MODEL
    if selected_model not in whisper_instances:
        whisper_instances[selected_model] = CodeWhisper(
            model_name=selected_model,
            download_root=settings.SPEECH_MODEL_DIR or None,
        )
    return whisper_instances[selected_model]


def build_transcribe_response(
    whisper: CodeWhisper,
    result: dict[str, Any],
    *,
    language: str,
    include_details: bool,
    include_corrections: bool,
) -> dict[str, Any]:
    corrections = whisper.dict_manager.get_corrections() if include_corrections else []
    return {
        "success": True,
        "text": (result.get("text") or "").strip(),
        "language": result.get("language", language),
        "corrections": {
            "count": len(corrections),
            "details": corrections if include_details else [],
        },
    }


def store_audio(content: bytes, suffix: str, original_filename: str) -> tuple[str, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_name = Path(original_filename or f"audio{suffix}").name
    saved_file = AUDIO_STORAGE_DIR / f"{timestamp}_{safe_name}"
    saved_file.write_bytes(content)

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        return tmp.name, saved_file


def create_app() -> FastAPI:
    app = FastAPI(
        title="Speech Services API",
        version="1.0.0",
        description="Speech recognition service for mold_main unified backend",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS_LIST or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


@router.get("/api/speech")
async def speech_root() -> dict[str, Any]:
    return {
        "name": "Speech Services API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "transcribe": "/api/transcribe",
            "transcribe_stream": "/api/transcribe/stream",
            "health": "/api/speech/health",
            "models": "/api/speech/models",
            "stats": "/api/speech/stats",
            "websocket": "/ws/transcribe",
        },
    }


@router.get("/")
async def legacy_root() -> dict[str, Any]:
    return await speech_root()


@router.get("/api/speech/health")
async def speech_health() -> dict[str, Any]:
    model_cache_dir = None
    if whisper_instances:
        first_instance = next(iter(whisper_instances.values()))
        model_cache_dir = getattr(first_instance, "download_root", None)

    return {
        "status": "healthy",
        "service": "speech_services",
        "loaded_models": list(whisper_instances.keys()),
        "gpu_available": GPU_AVAILABLE,
        "device": "cuda" if GPU_AVAILABLE else "cpu",
        "model_cache_dir": model_cache_dir,
    }


@router.get("/api/health")
async def legacy_speech_health() -> dict[str, Any]:
    return await speech_health()


@router.get("/api/speech/models")
async def speech_models() -> dict[str, Any]:
    return {
        "models": sorted(SUPPORTED_MODELS),
        "default": settings.SPEECH_DEFAULT_MODEL,
        "loaded": list(whisper_instances.keys()),
    }


@router.get("/api/models")
async def legacy_speech_models() -> dict[str, Any]:
    return await speech_models()


@router.post("/api/transcribe")
@router.post("/api/speech/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: str = Form(settings.SPEECH_DEFAULT_MODEL),
    language: str = Form(settings.SPEECH_DEFAULT_LANGUAGE),
    fix_terms: bool = Form(True),
    learn: bool = Form(True),
    verbose: bool = Form(False),
) -> JSONResponse:
    if model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {suffix or 'unknown'}",
        )

    temp_file = None
    try:
        content = await file.read()
        temp_file, _ = store_audio(content, suffix, file.filename or f"audio{suffix}")
        whisper = get_whisper_instance(model)
        result = whisper.transcribe(
            temp_file,
            language=language,
            fix_programmer_terms=fix_terms,
            learn_user_terms=learn,
            verbose=verbose,
        )
        response = build_transcribe_response(
            whisper,
            result,
            language=language,
            include_details=verbose,
            include_corrections=fix_terms,
        )
        if verbose:
            response["stats"] = {
                "model": model,
                "file_size": len(content),
                "file_type": suffix,
                "dict_rules": whisper.get_dict_stats().get("total_rules", 0),
            }
        return JSONResponse(content=response)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        if temp_file:
            Path(temp_file).unlink(missing_ok=True)


@router.post("/api/transcribe/stream")
@router.post("/api/speech/transcribe/stream")
async def transcribe_stream(
    audio_data: str = Form(...),
    model: str = Form(settings.SPEECH_DEFAULT_MODEL),
    language: str = Form(settings.SPEECH_DEFAULT_LANGUAGE),
    fix_terms: bool = Form(True),
    format: str = Form("wav"),
) -> JSONResponse:
    if model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")

    suffix = f".{format.strip('.').lower()}"
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {suffix}")

    temp_file = None
    try:
        audio_bytes = base64.b64decode(audio_data)
        temp_file, _ = store_audio(audio_bytes, suffix, f"stream{suffix}")
        whisper = get_whisper_instance(model)
        result = whisper.transcribe(
            temp_file,
            language=language,
            fix_programmer_terms=fix_terms,
            verbose=False,
        )
        response = build_transcribe_response(
            whisper,
            result,
            language=language,
            include_details=True,
            include_corrections=fix_terms,
        )
        return JSONResponse(content=response)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stream transcription failed: {exc}") from exc
    finally:
        if temp_file:
            Path(temp_file).unlink(missing_ok=True)


@router.get("/api/speech/stats")
async def speech_stats() -> dict[str, Any]:
    if not whisper_instances:
        return {"loaded_models": [], "message": "No speech model loaded yet"}

    whisper = next(iter(whisper_instances.values()))
    audio_files = [path for path in AUDIO_STORAGE_DIR.glob("*") if path.is_file()]
    total_size = sum(path.stat().st_size for path in audio_files)

    return {
        "loaded_models": list(whisper_instances.keys()),
        "dict_stats": whisper.get_dict_stats(),
        "dict_categories": whisper.get_dict_categories(),
        "audio_storage": {
            "directory": str(AUDIO_STORAGE_DIR.relative_to(PROJECT_ROOT)),
            "file_count": len(audio_files),
            "total_size": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        },
    }


@router.get("/api/stats")
async def legacy_speech_stats() -> dict[str, Any]:
    return await speech_stats()


@router.get("/api/speech/audio/list")
async def list_audio_files() -> dict[str, Any]:
    files = []
    for path in sorted(AUDIO_STORAGE_DIR.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "filename": path.name,
                "size": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 2),
                "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return {"total_count": len(files), "files": files}


@router.get("/api/audio/list")
async def legacy_list_audio_files() -> dict[str, Any]:
    return await list_audio_files()


@router.delete("/api/speech/audio/clean")
async def clean_audio_files(older_than_hours: int = Form(24)) -> dict[str, Any]:
    cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
    deleted_files: list[str] = []
    deleted_size = 0

    for path in AUDIO_STORAGE_DIR.glob("*"):
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime >= cutoff_time:
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        deleted_files.append(path.name)
        deleted_size += size

    return {
        "success": True,
        "deleted_count": len(deleted_files),
        "deleted_size": deleted_size,
        "deleted_size_mb": round(deleted_size / 1024 / 1024, 2),
        "cutoff_time": cutoff_time.isoformat(),
        "files": deleted_files,
    }


@router.delete("/api/audio/clean")
async def legacy_clean_audio_files(older_than_hours: int = Form(24)) -> dict[str, Any]:
    return await clean_audio_files(older_than_hours)


@router.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket) -> None:
    await websocket.accept()
    session: dict[str, Any] = {
        "model": settings.SPEECH_DEFAULT_MODEL,
        "language": settings.SPEECH_DEFAULT_LANGUAGE,
        "audio_chunks": [],
        "temp_file": None,
    }

    try:
        while True:
            payload = await websocket.receive_json()
            action = payload.get("action")

            if action == "start":
                session["model"] = payload.get("model", settings.SPEECH_DEFAULT_MODEL)
                session["language"] = payload.get("language", settings.SPEECH_DEFAULT_LANGUAGE)
                session["audio_chunks"] = []
                await websocket.send_json(
                    {
                        "type": "status",
                        "message": f"session started with model: {session['model']}",
                    }
                )
                continue

            if action == "audio":
                chunk = payload.get("data")
                if chunk:
                    session["audio_chunks"].append(chunk)
                    await websocket.send_json(
                        {
                            "type": "status",
                            "message": f"received chunk {len(session['audio_chunks'])}",
                        }
                    )
                continue

            if action == "end":
                if not session["audio_chunks"]:
                    await websocket.send_json({"type": "error", "message": "no audio data"})
                    continue

                try:
                    combined_audio = b"".join(base64.b64decode(chunk) for chunk in session["audio_chunks"])
                    temp_file, _ = store_audio(combined_audio, ".wav", "websocket.wav")
                    session["temp_file"] = temp_file
                    whisper = get_whisper_instance(session["model"])
                    result = whisper.transcribe(
                        temp_file,
                        language=session["language"],
                        fix_programmer_terms=True,
                        verbose=False,
                    )
                    response = build_transcribe_response(
                        whisper,
                        result,
                        language=session["language"],
                        include_details=True,
                        include_corrections=True,
                    )
                    await websocket.send_json(
                        {
                            "type": "result",
                            "text": response["text"],
                            "language": response["language"],
                            "corrections": response["corrections"],
                        }
                    )
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": f"transcription failed: {exc}"})
                finally:
                    if session["temp_file"]:
                        Path(session["temp_file"]).unlink(missing_ok=True)
                        session["temp_file"] = None
                    session["audio_chunks"] = []
                continue

            await websocket.send_json({"type": "error", "message": f"unsupported action: {action}"})
    except WebSocketDisconnect:
        return
    finally:
        if session["temp_file"]:
            Path(session["temp_file"]).unlink(missing_ok=True)


app = create_app()


def main() -> None:
    get_whisper_instance(settings.SPEECH_DEFAULT_MODEL)
    uvicorn.run(
        app,
        host=settings.SPEECH_HOST,
        port=settings.SPEECH_PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
