"""Check that a clean source export retains the runnable build entry point."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class SourceExportTests(unittest.TestCase):
    def test_clean_source_export_has_build_inputs_and_runs(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "workbench_source_export", root / "scripts" / "package_source.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        files = module.sources()
        with tempfile.TemporaryDirectory(prefix="workbench-source-export-") as temp:
            clean = Path(temp)
            for source in files:
                target = clean / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            for required in ("run.py", "scripts/build.ps1", "requirements-build-lock.txt"):
                self.assertTrue((clean / required).is_file(), required)
            result = subprocess.run(
                [sys.executable, "-E", "-S", str(clean / "run.py"), "--version"],
                cwd=clean, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "0.2.0.dev1")


if __name__ == "__main__":
    unittest.main()
