import unittest

import activity


class ActivityTests(unittest.TestCase):
    def tearDown(self):
        activity.clear()

    def test_remaining_bytes_during_a_download(self):
        activity.begin("download", "Speech model small")
        activity.note(25, 100)
        snap = activity.snapshot()
        self.assertTrue(snap["active"])
        self.assertEqual(snap["phase"], "download")
        self.assertEqual(snap["label"], "Speech model small")
        self.assertEqual(snap["remaining"], 75)

    def test_note_at_least_keeps_the_higher_received_count(self):
        activity.begin("download", "Speech model small")
        activity.note(10, 100)
        activity.note_at_least(40, 0)
        activity.note_at_least(25, 0)
        snap = activity.snapshot()
        self.assertEqual(snap["received"], 40)
        self.assertEqual(snap["total"], 100)
        self.assertEqual(snap["remaining"], 60)

    def test_note_at_least_can_raise_total_when_hub_learns_size(self):
        activity.begin("download", "Speech model small")
        activity.note_at_least(5, 0)
        activity.note_at_least(5, 80)
        snap = activity.snapshot()
        self.assertEqual(snap["received"], 5)
        self.assertEqual(snap["total"], 80)

    def test_clear_returns_to_idle(self):
        activity.begin("transcribe", "Transcribing")
        activity.clear()
        snap = activity.snapshot()
        self.assertFalse(snap["active"])
        self.assertEqual(snap["phase"], "idle")
        self.assertEqual(snap["remaining"], 0)

    def test_progress_keeps_transcribe_phase(self):
        activity.begin("transcribe", "Transcribing 0/4")
        activity.progress(2, 4)
        snap = activity.snapshot()
        self.assertEqual(snap["phase"], "transcribe")
        self.assertEqual(snap["label"], "Transcribing 0/4")
        self.assertEqual(snap["received"], 2)
        self.assertEqual(snap["total"], 4)
        self.assertEqual(snap["remaining"], 2)

    def test_progress_can_refresh_the_label(self):
        activity.begin("transcribe", "Transcribing")
        activity.progress(11200, 643406, label="Transcribing · 2% · 632k frames left")
        snap = activity.snapshot()
        self.assertEqual(snap["phase"], "transcribe")
        self.assertEqual(snap["label"], "Transcribing · 2% · 632k frames left")
        self.assertEqual(snap["received"], 11200)
        self.assertEqual(snap["total"], 643406)


if __name__ == "__main__":
    unittest.main()
