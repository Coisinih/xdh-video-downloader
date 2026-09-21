import os
import tempfile
from pathlib import Path

import pytest


_test_directory = tempfile.TemporaryDirectory(prefix="vidnest-tests-")
_test_root = Path(_test_directory.name)
os.environ["VIDNEST_DATABASE_PATH"] = str(_test_root / "vidnest.db")
os.environ["VIDNEST_DOWNLOAD_DIR"] = str(_test_root / "downloads")


@pytest.fixture(scope="session", autouse=True)
def isolated_application_storage():
    """Keep test runs deterministic and away from local development data."""
    yield
    _test_directory.cleanup()
