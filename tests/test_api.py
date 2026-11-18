import base64
import io
import json

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from mangum import Mangum
from PIL import Image

from chromatic import api
from chromatic.api import create_app
from chromatic.images import decode_image, encode_png
from chromatic.storage import LocalStore


@pytest.mark.parametrize("method", ["rgb", "covariance", "lalphabeta", "sliced"])
def test_end_to_end_and_cache(client, uploads, images, method):
    response = client.post("/api/v1/transfers", files=uploads, data={"method": method})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["width"] == 28 and result["height"] == 20 and not result["cached"]
    png = client.get(result["result_url"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert decode_image(png.content, 1000).shape == images[0].shape
    assert client.get(f"/api/v1/transfers/{result['id']}").json()["options"]["method"] == method
    again = client.post("/api/v1/transfers", files=uploads, data={"method": method})
    assert again.status_code == 200 and again.json()["cached"]
    assert again.json()["id"] == result["id"]


def test_app_recreation_can_read_durable_result(tmp_path, uploads):
    with TestClient(create_app(LocalStore(tmp_path), "")) as first:
        result = first.post("/api/v1/transfers", files=uploads).json()
    with TestClient(create_app(LocalStore(tmp_path), "")) as second:
        assert second.get(result["result_url"]).status_code == 200


def test_key_auth_and_public_health(tmp_path, uploads):
    with TestClient(create_app(LocalStore(tmp_path), "demo-key")) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        assert client.post("/api/v1/transfers", files=uploads).status_code == 401
        assert client.get("/api/v1/transfers/" + "a" * 64).status_code == 401
        headers = {"X-API-Key": "demo-key"}
        result = client.post("/api/v1/transfers", files=uploads, headers=headers)
        assert result.status_code == 201
        assert client.get(result.json()["result_url"], headers=headers).status_code == 200


@pytest.mark.parametrize(
    "data", [{"method": "bad"}, {"strength": "nan"}, {"iterations": "1000"}, {"seed": "-1"}]
)
def test_invalid_parameters(client, uploads, data):
    assert client.post("/api/v1/transfers", files=uploads, data=data).status_code == 422


def test_invalid_images_and_missing_upload(client, uploads):
    uploads["source"] = ("x.png", b"not an image", "image/png")
    assert client.post("/api/v1/transfers", files=uploads).status_code == 422
    assert (
        client.post("/api/v1/transfers", files={"reference": uploads["reference"]}).status_code
        == 422
    )
    assert client.get("/api/v1/transfers/not-an-id").status_code == 404
    assert client.get("/api/v1/transfers/" + "f" * 64).status_code == 404


def test_pixel_limit_precedes_decoding(client, uploads):
    oversized = np.zeros((513, 512, 3), dtype=np.uint8)
    uploads["source"] = ("big.png", encode_png(oversized), "image/png")
    response = client.post("/api/v1/transfers", files=uploads)
    assert response.status_code == 422 and "pixels" in response.json()["detail"]


def test_file_and_request_byte_limits(client, uploads):
    uploads["source"] = ("big.png", b"x" * (api.MAX_FILE_BYTES + 1), "image/png")
    assert client.post("/api/v1/transfers", files=uploads).status_code == 413
    response = client.post("/api/v1/transfers", content=b"x" * (api.MAX_REQUEST_BYTES + 1))
    assert response.status_code == 413


def test_body_limit_without_content_length(client):
    def chunks():
        for _ in range(5):
            yield b"x" * 1024 * 1024

    assert client.post("/api/v1/transfers", content=chunks()).status_code == 413


def test_storage_errors_return_retryable_status(uploads):
    class BrokenStore:
        def get(self, key):
            raise OSError("disk full; private path should not leak")

    with TestClient(create_app(BrokenStore(), "")) as client:
        response = client.post("/api/v1/transfers", files=uploads)
    assert response.status_code == 503 and "private" not in response.text


def test_cloud_mode_requires_key(monkeypatch):
    monkeypatch.setenv("COLOR_BUCKET", "demo-results")
    monkeypatch.delenv("COLOR_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="COLOR_API_KEY"):
        create_app()


def test_lambda_binary_response(client, uploads):
    result = client.post("/api/v1/transfers", files=uploads).json()
    handler = Mangum(client.app, lifespan="off")
    response = handler(
        {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": result["result_url"],
            "rawQueryString": "",
            "headers": {"host": "example.test"},
            "requestContext": {
                "http": {
                    "method": "GET",
                    "path": result["result_url"],
                    "sourceIp": "127.0.0.1",
                    "protocol": "HTTP/1.1",
                }
            },
            "isBase64Encoded": False,
        },
        {},
    )
    assert response["statusCode"] == 200 and response["isBase64Encoded"]
    assert base64.b64decode(response["body"]).startswith(b"\x89PNG")


def test_lambda_accepts_base64_multipart_uploads(client, uploads):
    request = httpx.Request(
        "POST", "https://example.test/api/v1/transfers", files=uploads, data={"method": "rgb"}
    )
    body = request.read()
    handler = Mangum(client.app, lifespan="off")
    response = handler(
        {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": "/api/v1/transfers",
            "rawQueryString": "",
            "headers": dict(request.headers),
            "requestContext": {
                "http": {
                    "method": "POST",
                    "path": "/api/v1/transfers",
                    "sourceIp": "127.0.0.1",
                    "protocol": "HTTP/1.1",
                }
            },
            "body": base64.b64encode(body).decode(),
            "isBase64Encoded": True,
        },
        {},
    )
    assert response["statusCode"] == 201
    metadata = json.loads(response["body"])
    assert metadata["options"]["method"] == "rgb"
    assert client.get(metadata["result_url"]).status_code == 200


def test_transparency_is_composited_and_unsupported_formats_rejected():
    stream = io.BytesIO()
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(stream, "PNG")
    assert np.all(decode_image(stream.getvalue(), 100) == 255)
    stream = io.BytesIO()
    Image.new("RGB", (4, 4)).save(stream, "GIF")
    with pytest.raises(ValueError, match="PNG and JPEG"):
        decode_image(stream.getvalue(), 100)


def test_chunked_middleware_and_disconnect():
    import asyncio

    async def exercise(messages, limit):
        sent, received = [], []

        async def receive():
            return messages.pop(0)

        async def send(event):
            sent.append(event)

        async def downstream(scope, receive, send):
            received.append(await receive())

        await api.BodyLimit(downstream, limit)({"type": "http", "method": "POST"}, receive, send)
        return sent, received

    sent, received = asyncio.run(
        exercise(
            [
                {"type": "http.request", "body": b"12", "more_body": True},
                {"type": "http.request", "body": b"34", "more_body": False},
            ],
            3,
        )
    )
    assert sent[0]["status"] == 413 and not received
    assert asyncio.run(exercise([{"type": "http.disconnect"}], 3)) == ([], [])
