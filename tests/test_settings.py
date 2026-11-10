import tempfile
import unittest
from pathlib import Path

import settings_store


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._original = settings_store.SETTINGS_PATH
        self._directory = tempfile.TemporaryDirectory()
        settings_store.SETTINGS_PATH = Path(self._directory.name) / "settings.json"

    def tearDown(self):
        settings_store.SETTINGS_PATH = self._original
        self._directory.cleanup()

    def test_defaults_when_nothing_is_saved(self):
        settings = settings_store.load_settings()
        self.assertEqual(settings["model"], "small.en")
        self.assertEqual(settings["device"], "auto")
        self.assertEqual(settings["compute_type"], "default")
        self.assertEqual(settings["language"], "en")
        self.assertEqual(settings["translate_to"], "fr")

    def test_custom_model_round_trip(self):
        saved = settings_store.save_settings(
            {
                "model": "large-v3",
                "device": "cuda",
                "compute_type": "float16",
                "cpu_threads": 8,
                "cluster_threshold": 0.4,
            }
        )
        self.assertEqual(saved["model"], "large-v3")
        self.assertEqual(settings_store.load_settings()["device"], "cuda")

    def test_unknown_device_is_rejected(self):
        with self.assertRaises(ValueError):
            settings_store.normalize({"model": "small.en", "device": "mps"})

    def test_empty_model_is_rejected(self):
        with self.assertRaises(ValueError):
            settings_store.normalize({"model": "  "})

    def test_unknown_language_is_rejected(self):
        with self.assertRaises(ValueError):
            settings_store.normalize({"model": "small.en", "language": "xx"})


if __name__ == "__main__":
    unittest.main()
