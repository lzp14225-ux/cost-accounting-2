from __future__ import annotations

import io
import hashlib
import os
import sys
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch
import uvicorn
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

SERVICE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SERVICE_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import settings

DEFAULT_COSYVOICE_ROOT = SERVICE_ROOT / "CosyVoice"
COSYVOICE_ROOT = Path(settings.COSYVOICE_ROOT).expanduser() if settings.COSYVOICE_ROOT else DEFAULT_COSYVOICE_ROOT
MATCHA_TTS_ROOT = COSYVOICE_ROOT / "third_party" / "Matcha-TTS"

for extra_path in (COSYVOICE_ROOT, MATCHA_TTS_ROOT):
    if extra_path.exists() and str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))

from cosyvoice.cli.cosyvoice import AutoModel
from cosyvoice.utils.file_utils import load_wav

GENERATED_AUDIO_DIR = SERVICE_ROOT / "audio"
GENERATED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_TTS_MODES = {"sft", "zero_shot", "cross_lingual", "instruct", "instruct2"}
GPU_AVAILABLE = torch.cuda.is_available()
cosyvoice_instances: dict[str, Any] = {}

router = APIRouter(tags=["tts"])


def resolve_model_dir(model_dir: str | None = None) -> Path:
    if model_dir:
        candidate = Path(model_dir).expanduser()
    elif settings.TTS_MODEL_DIR:
        candidate = Path(settings.TTS_MODEL_DIR).expanduser()
    else:
        candidate = COSYVOICE_ROOT / "pretrained_models" / "CosyVoice-300M-SFT"

    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    return candidate


def get_cosyvoice_instance(model_dir: str | None = None):
    resolved_model_dir = resolve_model_dir(model_dir)
    cache_key = str(resolved_model_dir)
    if cache_key not in cosyvoice_instances:
        if not COSYVOICE_ROOT.exists():
            raise RuntimeError(f"CosyVoice root not found: {COSYVOICE_ROOT}")
        if not resolved_model_dir.exists():
            raise RuntimeError(f"CosyVoice model dir not found: {resolved_model_dir}")
        cosyvoice_instances[cache_key] = AutoModel(model_dir=str(resolved_model_dir))
    return cosyvoice_instances[cache_key], resolved_model_dir


def merge_audio_chunks(model_output) -> tuple[np.ndarray, int]:
    chunks = []
    sample_rate = None
    for item in model_output:
        speech = item["tts_speech"].detach().cpu()
        if speech.ndim > 1:
            speech = speech.squeeze(0)
        chunks.append(speech)
        if sample_rate is None:
            sample_rate = int(item.get("sample_rate") or 0)
    if not chunks:
        raise RuntimeError("CosyVoice returned no audio chunks")
    waveform = torch.cat(chunks, dim=-1).numpy()
    return waveform, sample_rate or 24000


def waveform_to_wav_bytes(waveform: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(waveform, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def build_cache_key(
    *,
    text: str,
    mode: str,
    speaker: str | None,
    prompt_text: str | None,
    instruct_text: str | None,
    speed: float,
    model_dir: str | None,
    prompt_wav_bytes: bytes | None,
) -> str:
    digest = hashlib.sha256()
    for value in (
        text.strip(),
        mode.strip().lower(),
        speaker or "",
        prompt_text or "",
        instruct_text or "",
        f"{speed:.4f}",
        model_dir or "",
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    if prompt_wav_bytes:
        digest.update(prompt_wav_bytes)
    return digest.hexdigest()


def save_audio_file(content: bytes, filename: str | None = None, suffix: str = ".wav") -> Path:
    if filename:
        target = GENERATED_AUDIO_DIR / filename
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = GENERATED_AUDIO_DIR / f"{timestamp}{suffix}"
    target.write_bytes(content)
    return target


def clean_generated_audio_files(older_than_hours: int = 24 * 7) -> dict[str, Any]:
    cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
    deleted_files: list[str] = []
    deleted_size = 0

    for path in GENERATED_AUDIO_DIR.glob("*"):
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime >= cutoff_time:
            continue
        deleted_size += path.stat().st_size
        path.unlink(missing_ok=True)
        deleted_files.append(path.name)

    return {
        "success": True,
        "deleted_count": len(deleted_files),
        "deleted_size": deleted_size,
        "deleted_size_mb": round(deleted_size / 1024 / 1024, 2),
        "files": deleted_files,
        "cutoff_time": cutoff_time.isoformat(),
    }


def build_root_payload() -> dict[str, Any]:
    return {
        "name": "TTS Services API",
        "version": "1.0.0",
        "status": "running",
        "default_mode": settings.TTS_DEFAULT_MODE,
        "default_model_dir": str(resolve_model_dir()),
        "cosyvoice_root": str(COSYVOICE_ROOT),
        "endpoints": {
            "health": "/api/tts/health",
            "speakers": "/api/tts/speakers",
            "synthesize": "/api/tts/synthesize",
            "audio_list": "/api/tts/audio/list",
            "audio_clean": "/api/tts/audio/clean",
        },
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="TTS Services API",
        version="1.0.0",
        description="CosyVoice text-to-speech service for mold_main backend",
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


def run_tts_inference(
    *,
    text: str,
    mode: str,
    speaker: str | None,
    prompt_text: str | None,
    instruct_text: str | None,
    prompt_wav: UploadFile | None,
    speed: float,
    model_dir: str | None,
) -> tuple[bytes, int, Path]:
    cosyvoice, resolved_model_dir = get_cosyvoice_instance(model_dir)

    if mode == "sft":
        if not speaker:
            raise HTTPException(status_code=400, detail="speaker is required for sft mode")
        output = cosyvoice.inference_sft(text, speaker, stream=False, speed=speed)
    elif mode == "zero_shot":
        if not prompt_text:
            raise HTTPException(status_code=400, detail="prompt_text is required for zero_shot mode")
        if prompt_wav is None:
            raise HTTPException(status_code=400, detail="prompt_wav is required for zero_shot mode")
        prompt_speech = load_wav(prompt_wav.file, 16000)
        output = cosyvoice.inference_zero_shot(text, prompt_text, prompt_speech, stream=False, speed=speed)
    elif mode == "cross_lingual":
        if prompt_wav is None:
            raise HTTPException(status_code=400, detail="prompt_wav is required for cross_lingual mode")
        prompt_speech = load_wav(prompt_wav.file, 16000)
        output = cosyvoice.inference_cross_lingual(text, prompt_speech, stream=False, speed=speed)
    elif mode == "instruct":
        if not speaker:
            raise HTTPException(status_code=400, detail="speaker is required for instruct mode")
        if not instruct_text:
            raise HTTPException(status_code=400, detail="instruct_text is required for instruct mode")
        output = cosyvoice.inference_instruct(text, speaker, instruct_text, stream=False, speed=speed)
    elif mode == "instruct2":
        if not instruct_text:
            raise HTTPException(status_code=400, detail="instruct_text is required for instruct2 mode")
        if prompt_wav is None:
            raise HTTPException(status_code=400, detail="prompt_wav is required for instruct2 mode")
        prompt_speech = load_wav(prompt_wav.file, 16000)
        output = cosyvoice.inference_instruct2(text, instruct_text, prompt_speech, stream=False, speed=speed)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported TTS mode: {mode}")

    waveform, sample_rate = merge_audio_chunks(output)
    return waveform_to_wav_bytes(waveform, sample_rate), sample_rate, resolved_model_dir


@router.get("/api/tts")
async def tts_root() -> dict[str, Any]:
    return build_root_payload()


@router.get("/api/tts/health")
async def tts_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "tts_services",
        "gpu_available": GPU_AVAILABLE,
        "device": "cuda" if GPU_AVAILABLE else "cpu",
        "cosyvoice_root": str(COSYVOICE_ROOT),
        "default_model_dir": str(resolve_model_dir()),
        "loaded_models": list(cosyvoice_instances.keys()),
        "default_mode": settings.TTS_DEFAULT_MODE,
    }


@router.get("/api/tts/speakers")
async def list_speakers(model_dir: str | None = None) -> dict[str, Any]:
    cosyvoice, resolved_model_dir = get_cosyvoice_instance(model_dir)
    speakers = []
    if hasattr(cosyvoice, "list_available_spks"):
        speakers = list(cosyvoice.list_available_spks() or [])
    return {
        "model_dir": str(resolved_model_dir),
        "speaker_count": len(speakers),
        "speakers": speakers,
    }


@router.post("/api/tts/synthesize")
async def synthesize_text(
    text: str = Form(...),
    mode: str = Form(settings.TTS_DEFAULT_MODE),
    model_dir: str | None = Form(None),
    speaker: str | None = Form(None),
    prompt_text: str | None = Form(None),
    instruct_text: str | None = Form(None),
    speed: float = Form(1.0),
    save_audio: bool = Form(True),
    prompt_wav: UploadFile | None = File(None),
):
    normalized_mode = (mode or settings.TTS_DEFAULT_MODE).strip().lower()
    if normalized_mode not in SUPPORTED_TTS_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported TTS mode: {normalized_mode}")
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    clean_generated_audio_files(24 * 7)

    prompt_wav_bytes: bytes | None = None
    if prompt_wav is not None:
        prompt_wav_bytes = await prompt_wav.read()
        await prompt_wav.seek(0)

    cache_key = build_cache_key(
        text=text,
        mode=normalized_mode,
        speaker=speaker,
        prompt_text=prompt_text,
        instruct_text=instruct_text,
        speed=speed,
        model_dir=model_dir,
        prompt_wav_bytes=prompt_wav_bytes,
    )
    cached_filename = f"{cache_key}.wav"
    cached_path = GENERATED_AUDIO_DIR / cached_filename

    if save_audio and cached_path.exists():
        audio_bytes = cached_path.read_bytes()
        headers = {
            "X-TTS-Mode": normalized_mode,
            "X-TTS-Model-Dir": str(resolve_model_dir(model_dir)),
            "X-TTS-Cache-Hit": "true",
            "X-Saved-Audio-Path": str(cached_path),
            "Access-Control-Expose-Headers": "X-TTS-Mode,X-TTS-Sample-Rate,X-TTS-Model-Dir,X-Saved-Audio-Path,X-TTS-Cache-Hit",
        }
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
            headers=headers,
        )

    try:
        audio_bytes, sample_rate, resolved_model_dir = run_tts_inference(
            text=text,
            mode=normalized_mode,
            speaker=speaker,
            prompt_text=prompt_text,
            instruct_text=instruct_text,
            prompt_wav=prompt_wav,
            speed=speed,
            model_dir=model_dir,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {exc}") from exc

    saved_path = save_audio_file(audio_bytes, filename=cached_filename) if save_audio else None
    headers = {
        "X-TTS-Mode": normalized_mode,
        "X-TTS-Sample-Rate": str(sample_rate),
        "X-TTS-Model-Dir": str(resolved_model_dir),
        "X-TTS-Cache-Hit": "false",
        "Access-Control-Expose-Headers": "X-TTS-Mode,X-TTS-Sample-Rate,X-TTS-Model-Dir,X-Saved-Audio-Path,X-TTS-Cache-Hit",
    }
    if saved_path:
        headers["X-Saved-Audio-Path"] = str(saved_path)

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/wav",
        headers=headers,
    )


@router.get("/api/tts/audio/list")
async def list_generated_audio() -> dict[str, Any]:
    files = []
    for path in sorted(GENERATED_AUDIO_DIR.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
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


@router.delete("/api/tts/audio/clean")
async def clean_generated_audio(older_than_hours: int = Form(24 * 7)) -> dict[str, Any]:
    return clean_generated_audio_files(older_than_hours)


app = create_app()


@app.get("/")
async def root() -> dict[str, Any]:
    return build_root_payload()


def main() -> None:
    get_cosyvoice_instance()
    run_target = "tts_services.main:app" if settings.RELOAD else app
    uvicorn.run(
        run_target,
        host=settings.TTS_HOST,
        port=settings.TTS_PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
