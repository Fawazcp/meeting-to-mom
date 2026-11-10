"""Local tests for the validation and email formatting. No AWS calls are made.

Run from the project root:  python -m unittest discover -s tests
"""
import json
import os
import sys
import unittest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("MODEL_ID", "test-model")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extract_mom"))

import app  # noqa: E402

GOOD = {
    "summary": "Migration plan agreed.",
    "decisions": ["Blue-green cutover Saturday night"],
    "action_items": [
        {"task": "Rotate credentials", "owner": "Daniel", "due_date": "Wednesday, November eighteenth"},
        {"task": "Check payment alerts", "owner": None, "due_date": None},
    ],
}

TRANSCRIPT = ("spk_0: Daniel will rotate the credentials by Wednesday, November eighteenth. "
              "Somebody should check the payment alerts.")

# what the validator returns for GOOD: report-only fields get safe defaults
GOOD_NORMALISED = {
    **GOOD,
    "action_items": [dict(i, due_date_quote=None) for i in GOOD["action_items"]],
    "title": None, "meeting_date": None, "mode": None, "client": None,
    "purpose": None, "attendees": [], "discussion_items": [],
}


class ValidateTests(unittest.TestCase):
    def test_accepts_good_json(self):
        self.assertEqual(app.parse_and_validate(json.dumps(GOOD)), GOOD_NORMALISED)

    def test_accepts_code_fenced_json(self):
        fenced = "```json\n" + json.dumps(GOOD) + "\n```"
        self.assertEqual(app.parse_and_validate(fenced), GOOD_NORMALISED)

    def test_rejects_missing_owner_field(self):
        bad = json.loads(json.dumps(GOOD))
        del bad["action_items"][0]["owner"]
        with self.assertRaises(ValueError):
            app.parse_and_validate(json.dumps(bad))

    def test_rejects_wrong_type(self):
        bad = json.loads(json.dumps(GOOD))
        bad["decisions"] = "not a list"
        with self.assertRaises(ValueError):
            app.parse_and_validate(json.dumps(bad))

    def test_rejects_non_json(self):
        with self.assertRaises(json.JSONDecodeError):
            app.parse_and_validate("Here are your minutes: ...")


class HardeningTests(unittest.TestCase):
    def _item(self, **kw):
        base = {"task": "t", "owner": None, "due_date": None}
        base.update(kw)
        return json.dumps({"summary": "s", "decisions": [], "action_items": [base]})

    def test_top_level_list_is_a_value_error(self):
        with self.assertRaises(ValueError):
            app.parse_and_validate("[1, 2]")

    def test_non_object_action_item_is_a_value_error(self):
        raw = json.dumps({"summary": "s", "decisions": [], "action_items": ["x"]})
        with self.assertRaises(ValueError):
            app.parse_and_validate(raw)

    def test_decisions_must_be_strings(self):
        raw = json.dumps({"summary": "s", "decisions": [1], "action_items": []})
        with self.assertRaises(ValueError):
            app.parse_and_validate(raw)

    def test_null_like_strings_become_none(self):
        mom = app.parse_and_validate(self._item(owner="null", due_date=" Unassigned "))
        self.assertIsNone(mom["action_items"][0]["owner"])
        self.assertIsNone(mom["action_items"][0]["due_date"])

    def test_text_around_json_is_stripped(self):
        mom = app.parse_and_validate("Here you go: " + json.dumps(GOOD) + " Hope it helps")
        self.assertEqual(mom, GOOD_NORMALISED)

    def test_retry_also_covers_wrong_shape(self):
        answers = ["[1]", json.dumps(GOOD)]
        calls = []
        original = app.ask_model
        app.ask_model = lambda t, feedback=None: (calls.append(feedback), answers[len(calls) - 1])[1]
        try:
            self.assertEqual(app.extract_with_retry(TRANSCRIPT), GOOD_NORMALISED)
        finally:
            app.ask_model = original
        self.assertEqual(len(calls), 2)


class TranscriptTests(unittest.TestCase):
    def _data(self, with_labels=True):
        def w(text, start, kind="pronunciation"):
            it = {"type": kind, "alternatives": [{"content": text}]}
            if kind == "pronunciation":
                it["start_time"] = start
            return it
        data = {"results": {
            "transcripts": [{"transcript": "Hi Priya. Hello."}],
            "items": [w("Hi", "0.1"), w("Priya", "0.5"), w(".", None, "punctuation"), w("Hello", "1.0"), w(".", None, "punctuation")],
        }}
        if with_labels:
            data["results"]["speaker_labels"] = {"segments": [
                {"items": [{"start_time": "0.1", "speaker_label": "spk_0"}, {"start_time": "0.5", "speaker_label": "spk_0"}]},
                {"items": [{"start_time": "1.0", "speaker_label": "spk_1"}]},
            ]}
        return data

    def test_builds_speaker_lines(self):
        self.assertEqual(app.build_transcript(self._data()), "spk_0: Hi Priya.\nspk_1: Hello.")

    def test_falls_back_without_labels(self):
        self.assertEqual(app.build_transcript(self._data(False)), "Hi Priya. Hello.")


class FakeS3:
    """Stands in for boto3's S3 client so no AWS call is made."""
    def __init__(self):
        self.puts = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts[Key] = Body

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://example.invalid/{Params['Key']}?expires={ExpiresIn}"


class HandlerTests(unittest.TestCase):
    def test_handler_writes_pdf_draft_and_returns_email(self):
        o_load, o_ask, o_s3 = app.load_transcript, app.ask_model, app.s3
        fake = FakeS3()
        app.load_transcript = lambda key: "spk_0: hi"
        app.ask_model = lambda t, feedback=None: json.dumps(GOOD)
        app.s3 = fake
        try:
            out = app.handler({"transcriptKey": "transcripts/mom-call.json", "audioKey": "uploads/call.mp3"}, None)
        finally:
            app.load_transcript, app.ask_model, app.s3 = o_load, o_ask, o_s3
        self.assertEqual(out["emailSubject"], "MOM draft ready: call.mp3")
        self.assertEqual(out["pdfKey"], "mom/mom-call.pdf")
        self.assertTrue(fake.puts["mom/mom-call.pdf"].startswith(b"%PDF"))
        self.assertIn("mom/mom-call-draft.txt", fake.puts)
        self.assertIn("https://example.invalid/mom/mom-call.pdf", out["emailBody"])
        self.assertIn("----- EMAIL DRAFT", out["emailBody"])
        self.assertIn("Owner: UNASSIGNED", out["emailBody"])
        self.assertNotIn("example.invalid", fake.puts["mom/mom-call-draft.txt"].decode())


class PdfTests(unittest.TestCase):
    def test_pdf_builds_with_empty_and_unicode_content(self):
        mom = dict(GOOD_NORMALISED, title="Caf\u00e9 \u2013 review \u201cquoted\u201d \u4e2d")
        data = app.build_pdf(mom)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)


class RetryTests(unittest.TestCase):
    def test_retries_once_then_succeeds(self):
        answers = ["not json", json.dumps(GOOD)]
        calls = []

        def fake_ask(transcript, feedback=None):
            calls.append(feedback)
            return answers[len(calls) - 1]

        original = app.ask_model
        app.ask_model = fake_ask
        try:
            self.assertEqual(app.extract_with_retry(TRANSCRIPT), GOOD_NORMALISED)
        finally:
            app.ask_model = original
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(calls[1])  # second call carried the error message

    def test_fails_after_second_bad_answer(self):
        original = app.ask_model
        app.ask_model = lambda transcript, feedback=None: "still not json"
        try:
            with self.assertRaises(json.JSONDecodeError):
                app.extract_with_retry(TRANSCRIPT)
        finally:
            app.ask_model = original


class DateGroundingTests(unittest.TestCase):
    """The first real run turned the transcript's 'November 201' into '20th'."""

    def _mom(self, **kw):
        mom = json.loads(json.dumps(GOOD_NORMALISED))
        mom.update(kw)
        return mom

    def test_grounded_dates_pass(self):
        self.assertEqual(app.ungrounded_dates(self._mom(), TRANSCRIPT), [])

    def test_changed_due_date_is_flagged(self):
        mom = self._mom()
        mom["action_items"][0]["due_date"] = "Wednesday, November 19th"
        self.assertEqual(app.ungrounded_dates(mom, TRANSCRIPT), ["Wednesday, November 19th"])

    def test_weekday_date_in_decision_is_flagged(self):
        transcript = "The cutover window is Saturday, November 201. Rotate by Wednesday, November eighteenth."
        mom = self._mom(decisions=["Cutover on Saturday, November 20th"])
        self.assertEqual(app.ungrounded_dates(mom, transcript), ["Saturday, November 20th"])

    def test_prefix_of_a_longer_number_is_flagged(self):
        # real Run 2 case: model wrote "November 20", transcript says "November 201"
        transcript = "The cutover window is Saturday, November 201. Daniel rotates by Wednesday, November eighteenth."
        mom = self._mom(decisions=["Cutover on Saturday, November 20"])
        self.assertEqual(app.ungrounded_dates(mom, transcript), ["Saturday, November 20"])

    def test_ordinal_suffix_difference_is_not_flagged(self):
        mom = self._mom()
        mom["action_items"][0]["due_date"] = "Wednesday, November 18"
        self.assertEqual(app.ungrounded_dates(mom, "by Wednesday, November 18th"), [])

    def test_date_hidden_in_task_text_is_detected(self):
        mom = self._mom()
        mom["action_items"][0].update(task="Rotate credentials by Wednesday, November 18th", due_date=None)
        self.assertEqual(app.dates_hidden_in_tasks(mom), ["Rotate credentials by Wednesday, November 18th"])

    def test_modal_verb_may_is_not_a_date(self):
        mom = self._mom()
        mom["action_items"][1]["task"] = "Check whether alerts may cover payments"
        self.assertEqual(app.dates_hidden_in_tasks(mom), [])

    def test_retry_gets_the_date_feedback_then_succeeds(self):
        bad = json.loads(json.dumps(GOOD))
        bad["action_items"][0]["due_date"] = "Wednesday, November 19th"
        answers, calls = [json.dumps(bad), json.dumps(GOOD)], []
        original = app.ask_model
        app.ask_model = lambda t, feedback=None: (calls.append(feedback), answers[len(calls) - 1])[1]
        try:
            mom = app.extract_with_retry(TRANSCRIPT)
        finally:
            app.ask_model = original
        self.assertIn("Wednesday, November 19th", calls[1])
        self.assertNotIn("warnings", mom)

    def test_still_ungrounded_after_retry_is_kept_with_warning(self):
        bad = json.loads(json.dumps(GOOD))
        bad["action_items"][0]["due_date"] = "Wednesday, November 19th"
        original = app.ask_model
        app.ask_model = lambda t, feedback=None: json.dumps(bad)
        try:
            mom = app.extract_with_retry(TRANSCRIPT)
        finally:
            app.ask_model = original
        self.assertEqual(len(mom["warnings"]), 1)
        self.assertIn("November 19th", mom["warnings"][0])
        self.assertIn("CHECK BEFORE SENDING", app.build_draft(mom, "c.mp3", "u", "s3://b/k")[0])


class HindiTests(unittest.TestCase):
    HINDI = "arjun: मेरे सहकर्मी डेनियल बुधवार, अठारह नवंबर तक credentials rotate कर देंगे।"

    def _mom(self, due, quote):
        mom = json.loads(json.dumps(GOOD_NORMALISED))
        mom["action_items"][0].update(due_date=due, due_date_quote=quote)
        return mom

    def test_english_date_with_a_real_hindi_quote_passes(self):
        mom = self._mom("Wednesday, November 18", "बुधवार, अठारह नवंबर")
        self.assertEqual(app.ungrounded_dates(mom, self.HINDI), [])

    def test_quote_not_in_transcript_is_flagged(self):
        mom = self._mom("Wednesday, November 18", "बुधवार, उन्नीस नवंबर")
        self.assertEqual(app.ungrounded_dates(mom, self.HINDI), ["Wednesday, November 18"])

    def test_missing_quote_is_flagged_for_hindi(self):
        mom = self._mom("Wednesday, November 18", None)
        self.assertEqual(app.ungrounded_dates(mom, self.HINDI), ["Wednesday, November 18"])

    def test_english_transcript_still_needs_the_verbatim_date(self):
        mom = self._mom("Wednesday, November 19th", "anything")
        self.assertEqual(app.ungrounded_dates(mom, TRANSCRIPT), ["Wednesday, November 19th"])

    def test_hindi_left_in_the_english_output_triggers_the_retry_feedback(self):
        mom = json.loads(json.dumps(GOOD_NORMALISED))
        mom["summary"] = "\u0928\u092e\u0938\u094d\u0924\u0947"
        feedback, warnings = app._soft_problems(mom, TRANSCRIPT)
        self.assertIn("English", feedback)
        self.assertEqual(len(warnings), 1)

    def test_hindi_quote_field_does_not_trigger_the_english_warning(self):
        mom = self._mom("Wednesday, November 18", "बुधवार, अठारह नवंबर")
        feedback, warnings = app._soft_problems(mom, self.HINDI)
        self.assertEqual((feedback, warnings), ("", []))

    def test_missing_quote_feedback_asks_for_the_original_words(self):
        mom = self._mom("Wednesday, November 18", None)
        feedback, _ = app._soft_problems(mom, self.HINDI)
        self.assertIn("due_date_quote", feedback)

    def test_impossible_day_number_is_warned_not_retried(self):
        # real Nova Pro output copied "November 201" from the transcript (it is verbatim, so not 'ungrounded')
        mom = json.loads(json.dumps(GOOD_NORMALISED))
        mom["decisions"] = ["The cutover window is officially set for Saturday, November 201."]
        feedback, warnings = app._soft_problems(mom, "Saturday, November 201. " + TRANSCRIPT)
        self.assertEqual(feedback, "")
        self.assertEqual(len(warnings), 1)
        self.assertIn("November 201", warnings[0])

    def test_first_answer_with_only_a_warning_is_returned_with_it(self):
        mom = json.loads(json.dumps(GOOD))
        mom["decisions"] = ["Cutover on Saturday, November 201"]
        transcript = TRANSCRIPT + " Saturday, November 201"
        original = app.ask_model
        calls = []
        app.ask_model = lambda t, feedback=None: (calls.append(1), json.dumps(mom))[1]
        try:
            out = app.extract_with_retry(transcript)
        finally:
            app.ask_model = original
        self.assertEqual(len(calls), 1)  # no retry
        self.assertIn("November 201", out["warnings"][0])

    def test_pdf_builds_with_devanagari_in_the_data(self):
        # core PDF fonts are latin-1: unsupported characters become '?', but the build must not crash
        mom = dict(GOOD_NORMALISED, title="\u0928\u092e\u0938\u094d\u0924\u0947 meeting")
        self.assertTrue(app.build_pdf(mom).startswith(b"%PDF"))


class FormatTests(unittest.TestCase):
    def test_unassigned_and_no_date_are_shown(self):
        text = app.format_email(GOOD)
        self.assertIn("Owner: UNASSIGNED | Due: no date", text)
        self.assertIn("Owner: Daniel", text)


if __name__ == "__main__":
    unittest.main()
