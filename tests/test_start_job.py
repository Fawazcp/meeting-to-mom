"""Local test for start_job language settings. The Transcribe client is replaced: no AWS calls."""
import importlib.util
import os
import unittest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("BUCKET", "test-bucket")
PATH = os.path.join(os.path.dirname(__file__), "..", "src", "start_job", "app.py")


class Ctx:
    aws_request_id = "abcdef12-0000"


def load(languages):
    os.environ["TRANSCRIBE_LANGUAGES"] = languages
    spec = importlib.util.spec_from_file_location("start_job_app", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []
    mod.transcribe = type("T", (), {"start_transcription_job": lambda self, **kw: calls.append(kw)})()
    return mod, calls


EVENT = {"detail": {"object": {"key": "uploads/My Call.mp3"}}}


class StartJobTests(unittest.TestCase):
    def test_single_language_uses_language_code(self):
        mod, calls = load("en-US")
        out = mod.handler(EVENT, Ctx())
        self.assertEqual(calls[0]["LanguageCode"], "en-US")
        self.assertNotIn("IdentifyMultipleLanguages", calls[0])
        self.assertTrue(out["jobName"].startswith("mom-My-Call.mp3-"))

    def test_two_languages_use_multi_language_identification(self):
        mod, calls = load("hi-IN,en-IN")
        mod.handler(EVENT, Ctx())
        self.assertTrue(calls[0]["IdentifyMultipleLanguages"])
        self.assertEqual(calls[0]["LanguageOptions"], ["hi-IN", "en-IN"])
        self.assertNotIn("LanguageCode", calls[0])
        self.assertTrue(calls[0]["Settings"]["ShowSpeakerLabels"])


if __name__ == "__main__":
    unittest.main()
