import unittest

from alignment import SpeakerSpan, TimedText, assign_speakers


class AssignSpeakersTests(unittest.TestCase):
    def test_overlap_picks_the_speaker_who_talks_longest_in_the_line(self):
        segments = [TimedText(0.0, 4.0, "hello there")]
        spans = [
            SpeakerSpan(0.0, 1.0, 0),
            SpeakerSpan(1.0, 4.0, 1),
        ]
        turns = assign_speakers(segments, spans)
        self.assertEqual(turns[0]["speaker"], 1)
        self.assertEqual(turns[0]["text"], "hello there")

    def test_adjacent_lines_from_one_speaker_merge(self):
        segments = [
            TimedText(0.0, 1.0, "one"),
            TimedText(1.1, 2.0, "two"),
            TimedText(2.2, 3.0, "three"),
        ]
        spans = [
            SpeakerSpan(0.0, 2.1, 0),
            SpeakerSpan(2.1, 3.0, 1),
        ]
        turns = assign_speakers(segments, spans)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["text"], "one two")
        self.assertEqual(turns[1]["speaker"], 1)

    def test_blank_segments_are_dropped(self):
        turns = assign_speakers([TimedText(0.0, 1.0, "   ")], [])
        self.assertEqual(turns, [])

    def test_without_spans_everyone_is_speaker_zero(self):
        turns = assign_speakers([TimedText(0.2, 0.8, "only me")], [])
        self.assertEqual(turns[0]["speaker"], 0)


if __name__ == "__main__":
    unittest.main()
