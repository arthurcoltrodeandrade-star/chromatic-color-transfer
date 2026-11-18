"""Immutable result bundles. A single atomic object is the commit boundary."""

import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Protocol

from botocore.exceptions import ClientError


class Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, payload: bytes) -> None: ...


def valid_id(key: str) -> bool:
    return re.fullmatch(r"[a-f0-9]{64}", key) is not None


def _check_key(key: str) -> None:
    if not valid_id(key):
        raise ValueError("Invalid artifact ID")


def pack(metadata: dict, png: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("metadata.json", json.dumps(metadata, sort_keys=True))
        bundle.writestr("result.png", png)
    return buffer.getvalue()


def unpack(payload: bytes) -> tuple[dict, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        return json.loads(bundle.read("metadata.json")), bundle.read("result.png")


class LocalStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> bytes | None:
        _check_key(key)
        try:
            return (self.directory / f"{key}.zip").read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, payload: bytes) -> None:
        _check_key(key)
        # Publish a complete immutable file with one atomic hard-link operation.
        # A competing writer keeps the first committed bundle. No replacement of
        # open files is needed (important for concurrent readers on Windows).
        descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(name, self.directory / f"{key}.zip")
            except FileExistsError:
                pass
        finally:
            Path(name).unlink(missing_ok=True)


class S3Store:
    def __init__(self, bucket: str, client=None):
        import boto3

        self.bucket = bucket
        self.client = client if client is not None else boto3.client("s3")

    def get(self, key: str) -> bytes | None:
        _check_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=f"results/{key}.zip")
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                return None
            raise
        with response["Body"] as body:
            return body.read()

    def put(self, key: str, payload: bytes) -> None:
        _check_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=f"results/{key}.zip",
            Body=payload,
            ContentType="application/zip",
            ServerSideEncryption="AES256",
        )
