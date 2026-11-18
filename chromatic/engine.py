"""Numerical methods adapted from Arthur's color-transfer notebook.

`source` always means the image whose geometry is preserved; `reference`
always supplies the color distribution. All public inputs are uint8 RGB.
The notebook's log-LMS l-alpha-beta space is NOT CIE L*a*b*.
"""

from enum import StrEnum

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

ENGINE_VERSION = "1"
EPS = 1e-8
RGB_TO_LMS = np.array(
    [[0.3811, 0.5783, 0.0402], [0.1967, 0.7244, 0.0782], [0.0241, 0.1288, 0.8444]]
)
LMS_TO_RGB = np.linalg.inv(RGB_TO_LMS)
LOG_TO_LAB = np.diag([1 / np.sqrt(3), 1 / np.sqrt(6), 1 / np.sqrt(2)]) @ np.array(
    [[1, 1, 1], [1, 1, -2], [1, -1, 0]]
)
LAB_TO_LOG = np.linalg.inv(LOG_TO_LAB)


class Method(StrEnum):
    RGB = "rgb"
    LALPHABETA = "lalphabeta"
    COVARIANCE = "covariance"
    SLICED = "sliced"


class Options(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: Method = Method.COVARIANCE
    strength: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    iterations: int = Field(default=12, ge=1, le=30)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def _validate(image: np.ndarray) -> np.ndarray:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected an H x W x 3 uint8 RGB image")
    if image.shape[0] * image.shape[1] < 1:
        raise ValueError("Image must contain pixels")
    return image.reshape(-1, 3).astype(np.float64) / 255


def _match_moments(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    # Constant source channels cannot acquire texture. They map to the reference mean.
    std = x.std(axis=0)
    scale = np.divide(y.std(axis=0), std, out=np.zeros(3), where=std > EPS)
    return (x - x.mean(axis=0)) * scale + y.mean(axis=0)


def _matrix_power(cov: np.ndarray, power: float) -> np.ndarray:
    values, vectors = np.linalg.eigh(cov)
    return (vectors * np.maximum(values, EPS) ** power) @ vectors.T


def _covariance(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    xc, yc = x - x.mean(axis=0), y - y.mean(axis=0)
    # Population covariance works even for a one-pixel image.
    cx, cy = xc.T @ xc / len(x), yc.T @ yc / len(y)
    transform = _matrix_power(cy, 0.5) @ _matrix_power(cx, -0.5)
    return xc @ transform.T + y.mean(axis=0)


def _sliced(x: np.ndarray, y: np.ndarray, options: Options) -> np.ndarray:
    rng = np.random.default_rng(options.seed)
    result = x.copy()
    # Quantile interpolation supports different source/reference image sizes.
    qx = (np.arange(len(x)) + 0.5) / len(x)
    qy = (np.arange(len(y)) + 0.5) / len(y)
    for _ in range(options.iterations):
        basis, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        projected, reference = result @ basis, y @ basis
        for channel in range(3):
            order = np.argsort(projected[:, channel], kind="stable")
            projected[order, channel] = np.interp(qx, qy, np.sort(reference[:, channel]))
        result = 0.75 * result + 0.25 * (projected @ basis.T)
    return result


def transfer(source: np.ndarray, reference: np.ndarray, options: Options) -> np.ndarray:
    """Return RGB uint8 at exactly the source dimensions; never mutate inputs."""
    x, y = _validate(source), _validate(reference)
    if options.strength == 0 or np.array_equal(source, reference):
        return source.copy()
    match options.method:
        case Method.RGB:
            result = _match_moments(x, y)
        case Method.LALPHABETA:
            log_x = np.log10(np.maximum(x @ RGB_TO_LMS.T, EPS)) @ LOG_TO_LAB.T
            log_y = np.log10(np.maximum(y @ RGB_TO_LMS.T, EPS)) @ LOG_TO_LAB.T
            lab = _match_moments(log_x, log_y)
            result = (10 ** np.clip(lab @ LAB_TO_LOG.T, -8, 2)) @ LMS_TO_RGB.T
        case Method.COVARIANCE:
            result = _covariance(x, y)
        case Method.SLICED:
            result = _sliced(x, y, options)
        case _:
            raise ValueError("Unknown method")
    result = x + options.strength * (np.clip(result, 0, 1) - x)
    return np.rint(np.clip(result, 0, 1) * 255).astype(np.uint8).reshape(source.shape)
