from pathlib import Path

from software_company.tools_impl import _subprocess_env_for_project


def test_project_environment_exposes_portable_node_when_available(tmp_path: Path):
    env = _subprocess_env_for_project(tmp_path)
    node_dir = env.get("QUANTUM_SWARM_NODE_DIR")
    if node_dir:
        assert str(node_dir) in env["PATH"]
        assert (Path(node_dir) / "node.exe").is_file()
