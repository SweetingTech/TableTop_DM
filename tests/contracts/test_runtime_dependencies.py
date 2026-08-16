from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_save_crypto_runtime_dependency_is_declared():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]

    assert any(
        dependency.partition(">=")[0].lower() == "cryptography"
        for dependency in dependencies
    )
