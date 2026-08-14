import os
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from services.style_rag_service import _load_matrix  # noqa: E402


class FakeChunk:
    def __init__(self, values):
        self.embedding_blob = np.asarray(values, dtype=np.float32).tobytes()


def test_load_matrix_normalizes_vectors_without_changing_precision():
    matrix = _load_matrix([
        FakeChunk([3.0, 4.0]),
        FakeChunk([0.0, 0.0]),
    ])

    assert matrix.dtype == np.float32
    np.testing.assert_allclose(matrix[0], [0.6, 0.8], rtol=1e-6)
    np.testing.assert_array_equal(matrix[1], [0.0, 0.0])
