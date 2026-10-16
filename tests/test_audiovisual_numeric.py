import numpy as np

from app.services.audiovisual import _norm


def test_norm_never_returns_nan_or_infinity():
    values = np.asarray([0.0, float("nan"), float("inf"), float("-inf"), 1.0])
    result = _norm(values)
    assert np.isfinite(result).all()
