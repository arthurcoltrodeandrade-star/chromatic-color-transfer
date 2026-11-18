import numpy as np
import pytest
from pydantic import ValidationError

from chromatic.api import artifact_id
from chromatic.engine import Method, Options, transfer


@pytest.mark.parametrize("method", list(Method))
def test_identity_and_zero_strength_are_exact(images, method):
    source, reference = images
    assert np.array_equal(transfer(source, source, Options(method=method)), source)
    assert np.array_equal(transfer(source, reference, Options(method=method, strength=0)), source)


@pytest.mark.parametrize("method", list(Method))
def test_shape_range_determinism_and_no_mutation(images, method):
    source, reference = images
    original = source.copy()
    result = transfer(source, reference, Options(method=method))
    assert result.shape == source.shape and result.dtype == np.uint8
    assert np.array_equal(result, transfer(source, reference, Options(method=method)))
    assert np.array_equal(source, original)
    assert not np.array_equal(result, source)


@pytest.mark.parametrize("method", list(Method))
def test_constant_and_single_pixel_inputs_are_finite(method):
    source = np.zeros((1, 1, 3), dtype=np.uint8)
    reference = np.full((3, 2, 3), 180, dtype=np.uint8)
    with np.errstate(all="raise"):
        result = transfer(source, reference, Options(method=method))
    assert np.isfinite(result).all()


def test_rgb_matches_reference_channel_statistics(images):
    source, reference = images
    result = transfer(source, reference, Options(method=Method.RGB))
    np.testing.assert_allclose(result.mean((0, 1)), reference.mean((0, 1)), atol=0.1)
    # Rounding to uint8 changes each channel value by at most half a unit.
    np.testing.assert_allclose(result.std((0, 1)), reference.std((0, 1)), atol=0.5)


def test_covariance_matches_cross_channel_statistics():
    rng = np.random.default_rng(18)
    source = rng.integers(80, 160, (100, 100, 3), dtype=np.uint8)
    x = rng.normal(0, 10, (80, 90, 3))
    reference = np.rint(x @ np.array([[1, 0.4, 0.2], [0, 1, 0.4], [0.3, 0, 1]]) + 130)
    reference = reference.astype(np.uint8)
    result = transfer(source, reference, Options())
    np.testing.assert_allclose(
        np.cov(result.reshape(-1, 3), rowvar=False, bias=True),
        np.cov(reference.reshape(-1, 3), rowvar=False, bias=True),
        atol=0.7,
    )


def test_sliced_reduces_palette_mean_error(images):
    source, reference = images
    result = transfer(source, reference, Options(method=Method.SLICED, iterations=20))
    before = np.linalg.norm(source.mean((0, 1)) - reference.mean((0, 1)))
    after = np.linalg.norm(result.mean((0, 1)) - reference.mean((0, 1)))
    assert after < before / 10


@pytest.mark.parametrize(
    "image",
    [np.zeros((2, 2)), np.zeros((2, 2, 4), dtype=np.uint8), np.zeros((0, 2, 3), dtype=np.uint8)],
)
def test_rejects_invalid_arrays(image, images):
    with pytest.raises(ValueError):
        transfer(image, images[1], Options())


@pytest.mark.parametrize(
    "field,value",
    [("strength", float("nan")), ("iterations", 31), ("seed", -1), ("method", "unknown")],
)
def test_rejects_invalid_options(field, value):
    with pytest.raises(ValidationError):
        Options(**{field: value})


def test_result_identity_includes_options_and_pixels(images):
    source, reference = images
    key = artifact_id(source, reference, Options())
    assert key == artifact_id(source.copy(), reference.copy(), Options())
    assert key != artifact_id(source, reference, Options(strength=0.5))
    changed = source.copy()
    changed[0, 0, 0] += 1
    assert key != artifact_id(changed, reference, Options())
