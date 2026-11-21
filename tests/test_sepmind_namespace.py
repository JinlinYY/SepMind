"""Check renamed research entry points and persisted-session compatibility."""
import importlib

from api.main import SessionConfig


def test_public_namespace_and_design_entry_points():
    for name in (
        'sepmind.engineering.agents',
        'sepmind.engineering.topology.binary',
        'sepmind.engineering.topology.hybrid_autonomous',
        'sepmind.llm.backend_multimodel',
        'experiments.sepmind_controls.controller',
        'reproducibility.__main__',
    ):
        assert importlib.import_module(name).__name__ == name


def test_existing_session_identifier_is_normalized():
    assert SessionConfig().baseline == 'sepmind'
    assert SessionConfig(baseline='pha').baseline == 'sepmind'
