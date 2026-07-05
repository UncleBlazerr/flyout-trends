import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr_tracker.models import find_config


@pytest.fixture(scope="session")
def config():
    return find_config()
