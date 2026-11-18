"""HTTP boundary: validation, bounded uploads, auth and reproducible artifacts."""

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import APIKeyHeader

from chromatic.engine import ENGINE_VERSION, Method, Options, transfer
from chromatic.images import decode_image, encode_png
from chromatic.storage import LocalStore, S3Store, Store, pack, unpack, valid_id

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * MAX_FILE_BYTES + 64 * 1024
MAX_PIXELS = 512 * 512
log = logging.getLogger("chromatic")


class BodyLimit:
    """Enforce actual bytes, including chunked requests, before multipart parsing."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                return await JSONResponse({"detail": "Request too large"}, 413)(
                    scope, receive, send
                )
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)

        async def replay():
            nonlocal body
            if body is not None:
                value, body = body, None
                return {"type": "http.request", "body": value, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def artifact_id(source, reference, options: Options) -> str:
    digest = hashlib.sha256()
    digest.update(f"chromatic:{ENGINE_VERSION}".encode())
    digest.update(json.dumps(options.model_dump(mode="json"), sort_keys=True).encode())
    for image in (source, reference):
        digest.update(json.dumps(image.shape).encode())
        digest.update(image.tobytes())
    return digest.hexdigest()


def create_app(store: Store | None = None, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="Chromatic · Color Transfer API", version="0.1.0")
    key = os.getenv("COLOR_API_KEY", "") if api_key is None else api_key
    if store is None:
        bucket = os.getenv("COLOR_BUCKET")
        if bucket and not key:
            raise RuntimeError("COLOR_API_KEY is required for S3/cloud mode")
        store = (
            S3Store(bucket) if bucket else LocalStore(Path(os.getenv("COLOR_DATA_DIR", ".data")))
        )
    app.state.store = store
    app.add_middleware(BodyLimit, max_bytes=MAX_REQUEST_BYTES)
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(provided: Annotated[str | None, Depends(key_header)]):
        if key and (provided is None or not hmac.compare_digest(provided, key)):
            raise HTTPException(401, "Invalid or missing API key")

    def load(result_id: str):
        if not valid_id(result_id):
            raise HTTPException(404, "Result not found")
        payload = app.state.store.get(result_id)
        if payload is None:
            raise HTTPException(404, "Result not found")
        return unpack(payload)

    @app.exception_handler(ClientError)
    @app.exception_handler(BotoCoreError)
    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        log.error(json.dumps({"event": "storage_error", "type": type(exc).__name__}))
        return JSONResponse({"detail": "Artifact storage unavailable; retry later"}, 503)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/healthz")
    def health():
        return {"status": "ok", "engine_version": ENGINE_VERSION}

    @app.post("/api/v1/transfers", dependencies=[Depends(authorize)])
    def create_transfer(
        source: Annotated[UploadFile, File(description="Content image; geometry is preserved")],
        reference: Annotated[UploadFile, File(description="Image supplying the color palette")],
        method: Annotated[Method, Form()] = Method.COVARIANCE,
        strength: Annotated[float, Form(ge=0, le=1, allow_inf_nan=False)] = 1.0,
        iterations: Annotated[int, Form(ge=1, le=30)] = 12,
        seed: Annotated[int, Form(ge=0, le=2**32 - 1)] = 42,
    ):
        started = time.perf_counter()
        arrays = []
        for upload in (source, reference):
            data = upload.file.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, "Each image must be at most 2 MiB")
            try:
                arrays.append(decode_image(data, MAX_PIXELS))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        options = Options(method=method, strength=strength, iterations=iterations, seed=seed)
        result_id = artifact_id(*arrays, options)
        cached = app.state.store.get(result_id)
        if cached is not None:
            metadata, _ = unpack(cached)
        else:
            result = transfer(*arrays, options)
            metadata = {
                "id": result_id,
                "engine_version": ENGINE_VERSION,
                "options": options.model_dump(mode="json"),
                "width": result.shape[1],
                "height": result.shape[0],
                "reference_width": arrays[1].shape[1],
                "reference_height": arrays[1].shape[0],
                "processing_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            app.state.store.put(result_id, pack(metadata, encode_png(result)))
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        log.info(
            json.dumps(
                {
                    "event": "transfer",
                    "id": result_id,
                    "method": method,
                    "cached": cached is not None,
                    "elapsed_ms": elapsed,
                }
            )
        )
        return JSONResponse(
            {
                **metadata,
                "cached": cached is not None,
                "result_url": f"/api/v1/transfers/{result_id}/image",
            },
            status_code=200 if cached is not None else 201,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/transfers/{result_id}", dependencies=[Depends(authorize)])
    def metadata(result_id: str):
        value, _ = load(result_id)
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/transfers/{result_id}/image", dependencies=[Depends(authorize)])
    def result_image(result_id: str):
        _, png = load(result_id)
        return Response(
            png,
            media_type="image/png",
            headers={
                "Content-Disposition": 'inline; filename="chromatic-result.png"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


app = create_app()
