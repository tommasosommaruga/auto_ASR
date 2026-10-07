import tempfile
import unittest
from pathlib import Path

import chunked_uploads


class ChunkedUploadTests(unittest.TestCase):
    def setUp(self):
        self._original = chunked_uploads.UPLOAD_ROOT
        self._directory = tempfile.TemporaryDirectory()
        chunked_uploads.UPLOAD_ROOT = Path(self._directory.name)

    def tearDown(self):
        chunked_uploads.UPLOAD_ROOT = self._original
        self._directory.cleanup()

    def test_chunks_can_resume_and_assemble(self):
        payload = b"abcdefghijklmnopqrstuvwxyz012345"
        session = chunked_uploads.create_session(
            "clip.webm",
            len(payload),
            fingerprint="clip|32|1",
        )
        chunk_size = session["chunk_size"]
        # Force a tiny chunk size for the test by rewriting meta after create
        # is awkward; instead slice with the real chunk size for a small file —
        # one chunk covers the whole file. Use save_chunk with custom by
        # creating manually with patched CHUNK_SIZE.
        self.assertEqual(session["total_chunks"], 1)
        again = chunked_uploads.find_by_fingerprint("clip|32|1")
        self.assertEqual(again["id"], session["id"])
        chunked_uploads.save_chunk(session["id"], 0, payload)
        status = chunked_uploads.status(session["id"])
        self.assertTrue(status["complete"])
        path = chunked_uploads.assemble(session["id"])
        self.assertEqual(path.read_bytes(), payload)
        path.unlink(missing_ok=True)

    def test_partial_upload_lists_missing_chunks(self):
        old = chunked_uploads.CHUNK_SIZE
        chunked_uploads.CHUNK_SIZE = 10
        try:
            payload = b"0123456789ABCDEFGHIJ"
            session = chunked_uploads.create_session("a.wav", len(payload), "a|20|1")
            self.assertEqual(session["total_chunks"], 2)
            chunked_uploads.save_chunk(session["id"], 0, payload[:10])
            status = chunked_uploads.status(session["id"])
            self.assertEqual(status["received"], [0])
            self.assertFalse(status["complete"])
            chunked_uploads.save_chunk(session["id"], 1, payload[10:])
            path = chunked_uploads.assemble(session["id"])
            self.assertEqual(path.read_bytes(), payload)
            path.unlink(missing_ok=True)
        finally:
            chunked_uploads.CHUNK_SIZE = old

    def test_complete_session_is_found_by_name_and_size(self):
        old = chunked_uploads.CHUNK_SIZE
        chunked_uploads.CHUNK_SIZE = 10
        try:
            payload = b"0123456789ABCDEFGHIJ"
            session = chunked_uploads.create_session(
                "AUD-20261004-WA0000.m4a",
                len(payload),
                "AUD-20261004-WA0000.m4a|20|999",
            )
            chunked_uploads.save_chunk(session["id"], 0, payload[:10])
            chunked_uploads.save_chunk(session["id"], 1, payload[10:])
            # A later empty retry with a new lastModified must not win.
            empty = chunked_uploads.create_session(
                "AUD-20261004-WA0000.m4a",
                len(payload),
                "AUD-20261004-WA0000.m4a|20|111",
            )
            self.assertNotEqual(empty["id"], session["id"])
            best = chunked_uploads.find_best_for(
                "AUD-20261004-WA0000.m4a",
                len(payload),
                "AUD-20261004-WA0000.m4a|20|222",
            )
            self.assertEqual(best["id"], session["id"])
            self.assertTrue(best["complete"])
            chunked_uploads.prune_weaker_siblings(
                session["id"],
                "AUD-20261004-WA0000.m4a",
                len(payload),
            )
            # Empty retry is gone; complete session remains.
            remaining = chunked_uploads.list_sessions()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]["id"], session["id"])
        finally:
            chunked_uploads.CHUNK_SIZE = old

    def test_partial_beats_empty_retry(self):
        old = chunked_uploads.CHUNK_SIZE
        chunked_uploads.CHUNK_SIZE = 10
        try:
            payload = b"0123456789ABCDEFGHIJ"
            partial = chunked_uploads.create_session("talk.m4a", len(payload), "talk.m4a|20")
            chunked_uploads.save_chunk(partial["id"], 0, payload[:10])
            chunked_uploads.create_session("talk.m4a", len(payload), "talk.m4a|20")
            best = chunked_uploads.find_best_for("talk.m4a", len(payload), "talk.m4a|20")
            self.assertEqual(best["id"], partial["id"])
            self.assertEqual(best["bytes_received"], 10)
            self.assertFalse(best["complete"])
        finally:
            chunked_uploads.CHUNK_SIZE = old


if __name__ == "__main__":
    unittest.main()
