"""Smoke tests for the gimpsam package — stdlib only, no network, no root,
no Tk required."""

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class ImportTests(unittest.TestCase):
    def test_every_module_imports(self):
        import importlib

        for mod in ("constants", "util", "job", "gimp_dirs", "models",
                    "hardware", "backend", "sam3", "plugin", "cli"):
            importlib.import_module(f"gimpsam.{mod}")


class ModelRegistryTests(unittest.TestCase):
    def test_registry_is_consistent(self):
        from gimpsam.models import MODEL_BY_KEY, MODEL_REGISTRY

        self.assertGreater(len(MODEL_REGISTRY), 0)
        self.assertEqual(len(MODEL_BY_KEY), len(MODEL_REGISTRY))
        for spec in MODEL_REGISTRY:
            self.assertTrue(spec.key)
            self.assertIs(MODEL_BY_KEY[spec.key], spec)
            if spec.family != "SAM3":
                self.assertTrue(spec.filename and spec.url,
                                f"{spec.key}: only SAM3 may omit filename/url")

    def test_recommended_model_exists(self):
        from gimpsam.hardware import detect_hardware, recommended_model_key
        from gimpsam.models import MODEL_BY_KEY

        self.assertIn(recommended_model_key(detect_hardware()), MODEL_BY_KEY)


class PluginSourceTests(unittest.TestCase):
    def test_checkout_resolves_locally(self):
        """In a repo checkout the plug-in files sit next to the package, so
        resolution must never hit the network."""
        from gimpsam.plugin import resolve_plugin_sources

        sources = resolve_plugin_sources(job=None)  # job unused on the local path
        for fname, path in sources.items():
            self.assertTrue(Path(path).is_file(), fname)

    def test_default_ref_tracks_version(self):
        import gimpsam
        from gimpsam.plugin import default_ref

        self.assertEqual(default_ref(),
                         "main" if gimpsam.__version__.startswith("0.0.0")
                         else f"v{gimpsam.__version__}")


class CliTests(unittest.TestCase):
    def test_arg_parser_builds(self):
        from gimpsam.cli import build_arg_parser

        parser = build_arg_parser()
        with self.assertRaises(SystemExit) as ctx, \
                contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_module_entrypoint(self):
        proc = subprocess.run([sys.executable, "-m", "gimpsam", "--help"],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Segment Anything", proc.stdout)

    def test_status_runs_headless(self):
        proc = subprocess.run([sys.executable, "-m", "gimpsam", "status"],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SAM plug-in", proc.stdout)


if __name__ == "__main__":
    unittest.main()
