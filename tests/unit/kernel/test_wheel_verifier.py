from __future__ import annotations

import subprocess
import zipfile

import pytest

from scripts.verify_wheel import REQUIRED_MEMBERS, verify_extracted_runtime

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dimensions, status", [(79, 200), (80, 500)])
def test_broken_runtime_assets_fail_verification_even_with_python_optimization(
    monkeypatch, tmp_path, dimensions, status
):
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    wheel = tmp_path / "broken.whl"
    versions = [member.rsplit("/", 1)[1] for member in REQUIRED_MEMBERS if member.endswith(".sql")]
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in (
            "persona/__init__.py",
            "infra/__init__.py",
            "kernel/__init__.py",
            "kernel/api/__init__.py",
        ):
            archive.writestr(name, "")
        archive.writestr(
            "persona/registry.py",
            "from types import SimpleNamespace\n"
            "class PersonaSchemaRegistry:\n"
            "    @staticmethod\n"
            f"    def load_default(): return SimpleNamespace(dimensions=range({dimensions}))\n",
        )
        archive.writestr(
            "infra/migrate.py",
            "from types import SimpleNamespace\nDEFAULT_MIGRATIONS_DIR = '.'\n"
            f"def discover(root): return [SimpleNamespace(version=v) for v in {versions!r}]\n",
        )
        archive.writestr(
            "kernel/api/app.py",
            "from types import SimpleNamespace\n"
            f"def get(url): return SimpleNamespace(status_code={status}, "
            "data=b'<script src=\"/static/v2/assets/index-test.js\"></script>', "
            "content_type='application/javascript')\n"
            "def create_app(**kwargs): return SimpleNamespace("
            "test_client=lambda: SimpleNamespace(get=get))\n",
        )
    with pytest.raises(subprocess.CalledProcessError):
        verify_extracted_runtime(wheel)
