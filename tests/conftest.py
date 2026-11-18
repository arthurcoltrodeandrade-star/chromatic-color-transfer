import numpy as np
import pytest
from fastapi.testclient import TestClient

from chromatic.api import create_app
from chromatic.images import encode_png
from chromatic.storage import LocalStore


@pytest.fixture
def images():
    rng = np.random.default_rng(7)
    source = rng.integers(35, 110, (20, 28, 3), dtype=np.uint8)
    reference = rng.integers(130, 210, (17, 23, 3), dtype=np.uint8)
    return source, reference


@pytest.fixture
def uploads(images):
    return {
        name: (f"{name}.png", encode_png(image), "image/png")
        for name, image in zip(("source", "reference"), images, strict=True)
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(store=LocalStore(tmp_path), api_key="")) as client:
        yield client
