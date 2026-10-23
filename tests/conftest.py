import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cybertwin.model import build_network, load_raw  # noqa: E402


@pytest.fixture
def raw():
    return load_raw()


@pytest.fixture
def net(raw):
    return build_network(raw)
