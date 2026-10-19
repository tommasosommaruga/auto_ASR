import tempfile
import unittest
from pathlib import Path

import library


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self._original = library.LIBRARY
        self._directory = tempfile.TemporaryDirectory()
        library.LIBRARY = Path(self._directory.name)

    def tearDown(self):
        library.LIBRARY = self._original
        self._directory.cleanup()

    def _source(self, name: str) -> Path:
        path = Path(self._directory.name) / name
        path.write_bytes(b"audio")
        return path

    def test_saves_newest_first_and_titles_from_the_first_line(self):
        older = library.save_recording(
            self._source("a.webm"),
            {"turns": [{"speaker": 0, "start": 0, "end": 1, "text": "older line"}], "duration": 1},
        )
        meta_path = library.LIBRARY / older["id"] / "transcript.csv"
        text = meta_path.read_text(encoding="utf-8").replace(
            older["created_at"],
            "2000-01-01T00:00:00+00:00",
        )
        meta_path.write_text(text, encoding="utf-8")
        newer = library.save_recording(
            self._source("b.wav"),
            {
                "turns": [{"speaker": 0, "start": 0, "end": 2, "text": "newer line"}],
                "duration": 2,
            },
        )
        listed = library.list_recordings()
        self.assertEqual([item["id"] for item in listed], [newer["id"], older["id"]])
        self.assertEqual(newer["title"], "newer line")

    def test_preview_prefers_the_translation(self):
        saved = library.save_recording(
            self._source("translated.webm"),
            {
                "turns": [{
                    "speaker": 0,
                    "start": 0,
                    "end": 1,
                    "text": "hello there",
                    "translation": "bonjour",
                }],
                "duration": 1,
                "language": "en",
                "detected_language": "en",
                "translate_to": "fr",
            },
        )
        self.assertEqual(saved["title"], "bonjour")
        self.assertEqual(saved["preview"], "bonjour")
        self.assertEqual(library.list_recordings("bonjour")[0]["id"], saved["id"])

    def test_search_matches_later_transcript_lines(self):
        library.save_recording(
            self._source("c.webm"),
            {
                "turns": [
                    {"speaker": 0, "start": 0, "end": 1, "text": "hello"},
                    {"speaker": 1, "start": 1, "end": 2, "text": "budget review"},
                ],
                "duration": 2,
            },
        )
        self.assertEqual(len(library.list_recordings("budget")), 1)
        self.assertEqual(library.list_recordings("missing"), [])

    def test_rename_title_and_speaker_then_delete(self):
        saved = library.save_recording(
            self._source("d.m4a"),
            {"turns": [{"speaker": 0, "start": 0, "end": 1, "text": "hello"}], "duration": 1},
        )
        updated = library.update_recording(saved["id"], "Kitchen table", {"0": "Alex"})
        self.assertEqual(updated["title"], "Kitchen table")
        self.assertEqual(updated["speaker_names"]["0"], "Alex")
        self.assertTrue(library.audio_path(saved["id"]).is_file())
        library.delete_recording(saved["id"])
        self.assertEqual(library.list_recordings(), [])

    def test_a_comma_in_speech_round_trips_through_the_table(self):
        saved = library.save_recording(
            self._source("quoted.webm"),
            {
                "turns": [{
                    "speaker": 1,
                    "start": 0,
                    "end": 1.5,
                    "text": 'She said, "hello"',
                    "translation": "Elle a dit bonjour",
                }],
                "duration": 1.5,
            },
        )
        again = library.get_recording(saved["id"])
        self.assertEqual(again["turns"][0]["text"], 'She said, "hello"')
        self.assertEqual(again["turns"][0]["speaker"], 1)

    def test_editing_the_table_changes_the_next_import(self):
        saved = library.save_recording(
            self._source("edit.webm"),
            {"turns": [{"speaker": 0, "start": 0, "end": 1, "text": "hello there"}], "duration": 1},
        )
        library.update_recording(saved["id"], "Kept title", None)
        path = library.LIBRARY / saved["id"] / "transcript.csv"
        path.write_text(
            path.read_text(encoding="utf-8").replace("hello there", "hello friend"),
            encoding="utf-8",
        )
        again = library.get_recording(saved["id"])
        self.assertEqual(again["turns"][0]["text"], "hello friend")
        self.assertEqual(again["title"], "Kept title")

    def test_bad_id_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            library.get_recording("../secret")

    def test_cleaned_audio_is_optional_and_selectable(self):
        saved = library.save_recording(
            self._source("raw.webm"),
            {"turns": [], "duration": 2, "language": "en", "detected_language": "en"},
        )
        self.assertFalse(saved["has_cleaned"])
        self.assertEqual(saved["transcript_audio"], "original")
        cleaned = Path(self._directory.name) / "clean.wav"
        cleaned.write_bytes(b"cleaned-bytes")
        again = library.save_cleaned_audio(saved["id"], cleaned)
        self.assertTrue(again["has_cleaned"])
        self.assertTrue(library.audio_path(saved["id"], "cleaned").is_file())
        picked = library.set_transcript_audio(saved["id"], "cleaned")
        self.assertEqual(picked["transcript_audio"], "cleaned")
        library.delete_cleaned_audio(saved["id"])
        gone = library.get_recording(saved["id"])
        self.assertFalse(gone["has_cleaned"])
        self.assertEqual(gone["transcript_audio"], "original")

    def test_pending_upload_is_listed_without_transcript(self):
        saved = library.save_pending_recording(
            self._source("phone.m4a"),
            filename="AUD-meeting.m4a",
            language="en",
            translate_to="fr",
            num_speakers=2,
        )
        self.assertEqual(saved["status"], "pending")
        self.assertTrue(saved["pending"])
        self.assertEqual(saved["title"], "AUD-meeting")
        self.assertEqual(saved["turns"], [])
        listed = library.list_recordings()
        self.assertEqual(listed[0]["id"], saved["id"])
        self.assertTrue(listed[0]["pending"])
        audio = library.audio_path(saved["id"])
        self.assertTrue(audio.is_file())


if __name__ == "__main__":
    unittest.main()
