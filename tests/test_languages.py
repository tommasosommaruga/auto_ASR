import unittest

from languages import model_for_language


class ModelForLanguageTests(unittest.TestCase):
    def test_english_keeps_the_english_model(self):
        self.assertEqual(model_for_language("small.en", "en"), "small.en")

    def test_other_languages_use_the_multilingual_model(self):
        self.assertEqual(model_for_language("small.en", "fr"), "small")
        self.assertEqual(model_for_language("small.en", "auto"), "small")

    def test_a_multilingual_choice_stays(self):
        self.assertEqual(model_for_language("large-v3", "de"), "large-v3")


if __name__ == "__main__":
    unittest.main()
