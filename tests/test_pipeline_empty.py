"""No speech still keeps a usable result so the audio can be saved."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

import library
import parallel_transcribe
import pipeline
from alignment import TimedText


class EmptySpeechTests(unittest.TestCase):
    def setUp(self):
        self._original = library.LIBRARY
        self._directory = tempfile.TemporaryDirectory()
        library.LIBRARY = Path(self._directory.name)

    def tearDown(self):
        library.LIBRARY = self._original
        self._directory.cleanup()

    def test_library_keeps_audio_when_transcript_is_empty(self):
        source = Path(self._directory.name) / "quiet.webm"
        source.write_bytes(b"fake-audio-bytes")
        saved = library.save_recording(
            source,
            {
                "turns": [],
                "duration": 3.5,
                "model": "small",
                "device": "cpu",
                "language": "en",
                "detected_language": "en",
            },
        )
        self.assertEqual(saved["turns"], [])
        self.assertTrue(saved["title"].startswith("Recording "))
        self.assertEqual(saved["preview"], "")
        self.assertTrue(library.audio_path(saved["id"]).is_file())
        self.assertFalse(source.exists())

    def test_transcribe_returns_empty_turns_instead_of_failing(self):
        audio = np.zeros(16000, dtype=np.float32)
        model = MagicMock()
        info = MagicMock()
        info.language = "en"
        model.transcribe.return_value = (iter([]), info)

        with patch.object(pipeline, "load_mono_f32", return_value=audio), patch.object(
            pipeline, "ensure_diarization_models"
        ), patch.object(pipeline, "_get_whisper", return_value=(model, "cpu", "int8")), patch.object(
            pipeline, "_diarize", return_value=[]
        ):
            result = pipeline.transcribe_file(
                Path("quiet.webm"),
                {"model": "small", "language": "en", "device": "cpu",
                 "compute_type": "int8", "cpu_threads": 4, "cluster_threshold": 0.7},
                -1,
            )

        self.assertEqual(result["turns"], [])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["duration"], 1.0)
        self.assertEqual(result["model"], "small")

    def test_long_cpu_uses_parallel_path(self):
        audio = np.zeros(16000 * 200, dtype=np.float32)
        calls = {"n": 0}

        def fake_parallel(*_args, **_kwargs):
            calls["n"] += 1
            return [TimedText(0.0, 1.0, "hi")], "en"

        with patch.object(pipeline, "load_mono_f32", return_value=audio), patch.object(
            pipeline, "ensure_diarization_models"
        ), patch.object(pipeline, "resolve_device", return_value=("cpu", "int8")), patch.object(
            pipeline, "_transcribe_parallel_ct2", side_effect=fake_parallel
        ), patch.object(pipeline, "_transcribe_ct2") as single_mock, patch.object(
            pipeline, "_diarize", return_value=[]
        ):
            result = pipeline.transcribe_file(
                Path("long.webm"),
                {"model": "small", "language": "en", "device": "cpu",
                 "compute_type": "int8", "cpu_threads": 4, "cluster_threshold": 0.7},
                -1,
            )

        self.assertEqual(calls["n"], 1)
        single_mock.assert_not_called()
        self.assertEqual(result["turns"][0]["text"], "hi")

    def test_long_mlx_remaps_to_cpu_parallel(self):
        audio = np.zeros(16000 * 200, dtype=np.float32)
        seen = {}

        def fake_parallel(audio_arg, settings, requested, device, compute, **_kwargs):
            seen["device"] = device
            seen["compute"] = compute
            return [TimedText(0.0, 1.0, "hi")], "en"

        with patch.object(pipeline, "load_mono_f32", return_value=audio), patch.object(
            pipeline, "ensure_diarization_models"
        ), patch.object(pipeline, "resolve_device", return_value=("mlx", "float16")), patch.object(
            pipeline, "_transcribe_parallel_ct2", side_effect=fake_parallel
        ), patch.object(pipeline, "_transcribe_mlx") as mlx_mock, patch.object(
            pipeline, "_diarize", return_value=[]
        ):
            result = pipeline.transcribe_file(
                Path("long.webm"),
                {"model": "small", "language": "en", "device": "auto",
                 "compute_type": "default", "cpu_threads": 4, "cluster_threshold": 0.7},
                -1,
            )

        self.assertEqual(seen.get("device"), "cpu")
        self.assertEqual(seen.get("compute"), "int8")
        mlx_mock.assert_not_called()
        self.assertEqual(result["device"], "cpu")
        self.assertEqual(result["compute_type"], "int8")

    def test_cuda_second_model_oom_uses_one_worker(self):
        audio = np.zeros(16000 * 200, dtype=np.float32)
        settings = {
            "model": "small",
            "cpu_threads": 4,
        }
        load_count = {"n": 0}

        def fake_create(*_args, **_kwargs):
            load_count["n"] += 1
            if load_count["n"] == 2:
                raise RuntimeError("CUDA out of memory")
            return MagicMock()

        with patch.object(pipeline, "create_whisper_model", side_effect=fake_create), patch.object(
            parallel_transcribe, "transcribe_chunks", return_value=([], "en")
        ) as transcribe_mock:
            pipeline._transcribe_parallel_ct2(audio, settings, "en", "cuda", "float16")

        self.assertEqual(load_count["n"], 2)
        self.assertEqual(transcribe_mock.call_args.kwargs["worker_n"], 1)

    def test_cuda_second_model_non_oom_reraises(self):
        audio = np.zeros(16000 * 200, dtype=np.float32)
        settings = {
            "model": "small",
            "cpu_threads": 4,
        }
        load_count = {"n": 0}

        def fake_create(*_args, **_kwargs):
            load_count["n"] += 1
            if load_count["n"] == 2:
                raise ValueError("corrupt model weights")
            return MagicMock()

        with patch.object(pipeline, "create_whisper_model", side_effect=fake_create):
            with self.assertRaises(ValueError):
                pipeline._transcribe_parallel_ct2(audio, settings, "en", "cuda", "float16")


if __name__ == "__main__":
    unittest.main()
