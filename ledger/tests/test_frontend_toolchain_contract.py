from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NODE_ENGINE = "^20.19.0 || >=22.12.0"


def test_vite_node_engine_is_declared_in_package_and_lockfile() -> None:
    package = json.loads((REPOSITORY_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads(
        (REPOSITORY_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )

    assert package["engines"]["node"] == NODE_ENGINE
    assert lock["packages"][""]["engines"]["node"] == NODE_ENGINE


def test_frontend_quick_start_states_the_node_engine() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert f"Requires Node.js `{NODE_ENGINE}` for the Vite 8 toolchain." in readme
