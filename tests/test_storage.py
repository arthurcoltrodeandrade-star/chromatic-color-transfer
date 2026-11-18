import io
from concurrent.futures import ThreadPoolExecutor

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from chromatic.storage import LocalStore, S3Store, pack, unpack


def test_bundle_round_trip_and_concurrent_atomic_writes(tmp_path):
    store, key = LocalStore(tmp_path), "a" * 64
    bundles = [pack({"i": i}, bytes([i]) * 10000) for i in range(12)]

    def write(payload):
        store.put(key, payload)
        metadata, content = unpack(store.get(key))
        assert content == bytes([metadata["i"]]) * 10000

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, bundles))
    assert not list(tmp_path.glob(".pending-*"))
    assert store.get("b" * 64) is None
    with pytest.raises(ValueError):
        store.get("../../outside")


def test_s3_contract_with_stubbed_aws():
    client = boto3.client(
        "s3", region_name="eu-west-3", aws_access_key_id="test", aws_secret_access_key="test"
    )
    key, payload = "c" * 64, pack({"method": "rgb"}, b"png")
    path = f"results/{key}.zip"
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "bucket",
                "Key": path,
                "Body": payload,
                "ContentType": "application/zip",
                "ServerSideEncryption": "AES256",
            },
        )
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(payload), len(payload))},
            {"Bucket": "bucket", "Key": path},
        )
        stub.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            expected_params={"Bucket": "bucket", "Key": path},
        )
        stub.add_client_error(
            "get_object",
            service_error_code="AccessDenied",
            expected_params={"Bucket": "bucket", "Key": path},
        )
        store = S3Store("bucket", client)
        store.put(key, payload)
        assert store.get(key) == payload
        assert store.get(key) is None
        with pytest.raises(ClientError):
            store.get(key)
        stub.assert_no_pending_responses()
