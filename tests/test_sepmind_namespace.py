"""Check renamed research entry points and persisted-session compatibility."""
import importlib
from pathlib import Path

from api.main import SessionConfig


def test_public_namespace_and_design_entry_points():
    root = Path(__file__).resolve().parents[1]
    assert not (root / 'separation').exists()
    for name in (
        'sepmind.agent_runtime',
        'sepmind.engineering.agents',
        'sepmind.engineering.topology.binary',
        'sepmind.engineering.topology.hybrid_autonomous',
        'sepmind.llm.backend_multimodel',
        'sepmind.simulation.dwsim',
        'sepmind.shortcut.__main__',
        'experiments.sepmind_controls.controller',
        'reproducibility.__main__',
    ):
        assert importlib.import_module(name).__name__ == name


def test_existing_session_identifier_is_normalized():
    assert SessionConfig().baseline == 'sepmind'
    assert SessionConfig(baseline='pha').baseline == 'sepmind'
