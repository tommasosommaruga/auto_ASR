import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import translator
import pipeline
from pipeline import speech_cache_bytes, speech_can_download, speech_ready


class DownloadCatalogTests(unittest.TestCase):
    def tearDown(self):
        pipeline.drop_cached_model()

    def test_unknown_speech_model_is_not_on_disk(self):
        self.assertFalse(speech_ready("not-a-real-model"))

    def test_preset_speech_model_can_be_downloaded(self):
        self.assertTrue(speech_can_download("small.en"))

    def test_local_folder_cannot_be_downloaded(self):
        self.assertFalse(speech_can_download("/tmp/not-a-whisper-preset"))

    def test_pairs_are_read_from_package_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "translate-en_de-1_0"
            package.mkdir()
            (package / "metadata.json").write_text(
                json.dumps({"from_code": "en", "to_code": "de"}),
                encoding="utf-8",
            )
            self.assertEqual(translator.pairs_in(root), ["en:de"])

    def test_speech_cache_bytes_counts_incomplete_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / "model.bin.incomplete"
            partial.write_bytes(b"x" * 2048)
            self.assertEqual(speech_cache_bytes(str(root)), 2048)

    def test_missing_model_load_does_not_start_a_hub_download(self):
        settings = {
            "model": "medium.en",
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 2,
        }
        with patch.object(pipeline, "_ct2_speech_ready", return_value=False):
            with patch.object(pipeline, "snapshot_download") as snap:
                with patch.object(pipeline, "WhisperModel") as whisper:
                    with self.assertRaises(RuntimeError) as raised:
                        pipeline._get_whisper(settings)
                    self.assertIn("not installed", str(raised.exception))
                    snap.assert_not_called()
                    whisper.assert_not_called()

    def test_speech_install_uses_http_so_progress_can_move(self):
        from huggingface_hub import constants as hf_constants

        seen = {"disabled": None}

        def fake_download(*_args, **_kwargs):
            seen["disabled"] = hf_constants.HF_HUB_DISABLE_XET

        previous = hf_constants.HF_HUB_DISABLE_XET
        hf_constants.HF_HUB_DISABLE_XET = False
        try:
            with patch.object(pipeline, "speech_ready", return_value=False):
                with patch.object(pipeline, "_speech_download_total", return_value=0):
                    with patch.object(pipeline, "snapshot_download", side_effect=fake_download):
                        pipeline._ensure_cached_speech_model("medium.en")
            self.assertTrue(seen["disabled"])
            self.assertFalse(hf_constants.HF_HUB_DISABLE_XET)
        finally:
            hf_constants.HF_HUB_DISABLE_XET = previous

    def test_speech_install_locks_total_before_hub_adds_files(self):
        import activity

        activity.clear()
        seen = {"total": 0}

        def fake_download(*_args, **_kwargs):
            seen["total"] = activity.snapshot()["total"]

        with patch.object(pipeline, "speech_ready", return_value=False):
            with patch.object(pipeline, "_speech_download_total", return_value=1_500_000_000):
                with patch.object(pipeline, "snapshot_download", side_effect=fake_download):
                    pipeline._ensure_cached_speech_model("medium.en")
        self.assertEqual(seen["total"], 1_500_000_000)
        activity.clear()


if __name__ == "__main__":
    unittest.main()
