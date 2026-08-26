from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_model_inventory import load_frontend_official_artifact


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = REPOSITORY_ROOT / "src/data/official/export.unavailable.json"
OPENROUTER_PATH = (
    REPOSITORY_ROOT
    / "docs/data/model-discovery-snapshots/2026-08-25/openrouter.json"
)
HUGGINGFACE_PATH = (
    REPOSITORY_ROOT
    / "docs/data/model-discovery-snapshots/2026-08-25/huggingface-top100.json"
)


class ModelInventoryRehearsalTest(unittest.TestCase):
    def write_artifact(self, root: Path, mutate) -> None:
        artifact = json.loads(ARTIFACT_PATH.read_text())
        mutate(artifact)
        destination = root / "src/data/official/export.unavailable.json"
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(artifact))

    def test_rejects_mutated_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            self.write_artifact(
                root,
                lambda artifact: artifact.update(policyVersion="unapproved-policy"),
            )
            with self.assertRaisesRegex(ValueError, "unsupported policy version"):
                load_frontend_official_artifact(root)

    def test_rejects_mutated_canonical_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            self.write_artifact(
                root,
                lambda artifact: artifact["manifest"].update(contentSha256="0" * 64),
            )
            with self.assertRaisesRegex(ValueError, "digest does not match canonical content"):
                load_frontend_official_artifact(root)

    def test_fixed_epoch_generation_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            outputs = [root / "inventory-a.json", root / "inventory-b.json"]
            environment = {**os.environ, "SOURCE_DATE_EPOCH": "1787616000"}
            for output in outputs:
                subprocess.run(
                    [
                        sys.executable,
                        str(REPOSITORY_ROOT / "scripts/build_model_inventory.py"),
                        str(OPENROUTER_PATH),
                        str(HUGGINGFACE_PATH),
                        str(output),
                    ],
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            inventory = json.loads(outputs[0].read_text())
            self.assertEqual(inventory["schemaVersion"], "model-inventory-checkpoint-v2")
            self.assertTrue(inventory["syntheticDataRemoved"])
            self.assertEqual(inventory["counts"]["frontendOfficialArtifactModels"], 0)
            self.assertEqual(
                inventory["sources"]["frontendOfficialArtifact"]["artifactId"],
                "official-unavailable-containment-v1",
            )


if __name__ == "__main__":
    unittest.main()
