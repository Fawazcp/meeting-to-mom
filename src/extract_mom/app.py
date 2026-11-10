import json
import os
import re
import boto3
from botocore.config import Config

from mom_pdf import build_pdf

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
# let boto3 retry throttling a few times before the state machine sees an error
bedrock = boto3.client(
    "bedrock-runtime",
    config=Config(retries={"max_attempts": 5, "mode": "standard"}, read_timeout=60),
)
BUCKET = os.environ["BUCKET"]
MODEL_ID = os.environ["MODEL_ID"]
PREPARED_BY = os.environ.get("PREPARED_BY", "")
LINK_SECONDS = 6 * 3600  # a URL signed with role credentials may expire earlier, see README

SYSTEM_PROMPT = """You write minutes of meeting (MOM) from a transcript.
The transcript may be in English, Hindi (Devanagari script) or a mix of both.
Write EVERY field of your answer in English, whatever language the transcript uses. Translate meaning faithfully; never add facts that were not said.
Write people's names in Latin letters (for example Daniel, Priya).
The transcript has one line per turn, prefixed with an anonymous speaker label such as spk_0 or spk_1.
Return ONLY a JSON object, with no extra text, in exactly this shape:
{
  "title": "short meeting title or null",
  "meeting_date": "date and time exactly as stated in the transcript, or null",
  "mode": "how the meeting was held (for example Microsoft Teams, phone call) only if stated, else null",
  "client": "client or company name only if stated, else null",
  "purpose": "1-2 sentences on why the meeting was held",
  "summary": "2-3 sentences",
  "attendees": [{"name": "person who speaks or is named", "group": "company or team only if stated, else null"}],
  "decisions": ["key outcome or decision, one per string"],
  "discussion_items": [
    {"item": "short topic name", "discussion": "what was discussed, 1-3 sentences", "status": "decision or status for this topic, or null"}
  ],
  "action_items": [
    {"task": "what must be done", "owner": "name or null", "due_date": "date in English as spoken or null",
     "due_date_quote": "REQUIRED whenever due_date is set and the transcript is Hindi or mixed: the exact original words of the date copied from the transcript; otherwise null"}
  ]
}
Rules:
- Use null for any field the transcript does not state. Never guess a name, company, date or owner.
- For an English transcript, copy dates and numbers EXACTLY as written in the transcript, even if they look wrong or garbled (speech-to-text can make mistakes). Never correct, calculate, convert or complete a date.
- Go through the transcript turn by turn. Include EVERY commitment ("I will ...", "X will ...", "can you ...?") and every open task as its own action item, even small ones.
- An item that was discussed but not assigned still goes in action_items with owner null.
- Open tasks with no named person MUST still be listed, for example "somebody should check whether the alerts cover the payment service" becomes {"task": "check whether the alerts cover the payment service", "owner": null, "due_date": null}. Never drop them.
- Put a task's date ONLY in due_date. Keep dates out of the task text, and never leave due_date null when the transcript gives a date for that task.
- The owner is the person who accepts or is given the task. When a speaker says "I will ...", the owner is that speaker.
- Use a real name for a speaker ONLY if that speaker states their own name in the transcript. Otherwise use the label (for example "spk_0"). Never guess a name.
- List in attendees only people who speak or are named in the transcript.
- Ignore small talk."""


NULL_WORDS = {"", "null", "none", "n/a", "na", "unassigned", "unknown", "not specified", "not stated"}


def build_transcript(data):
    """Turn Transcribe JSON into 'spk_0: text' lines. Falls back to plain text without speaker labels."""
    results = data["results"]
    labels = results.get("speaker_labels")
    if not labels:
        return results["transcripts"][0]["transcript"]
    speaker_at = {}
    for seg in labels["segments"]:
        for it in seg["items"]:
            speaker_at[it["start_time"]] = it["speaker_label"]
    turns = []  # [speaker, [words]]
    for it in results["items"]:
        word = it["alternatives"][0]["content"]
        if it["type"] == "pronunciation":
            spk = speaker_at.get(it.get("start_time"), turns[-1][0] if turns else "spk_0")
            if not turns or turns[-1][0] != spk:
                turns.append([spk, []])
            turns[-1][1].append(word)
        elif turns and turns[-1][1]:  # punctuation sticks to the previous word
            turns[-1][1][-1] += word
    return "\n".join(f"{spk}: {' '.join(words)}" for spk, words in turns)


def load_transcript(key):
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    return build_transcript(json.loads(body))


def ask_model(transcript, feedback=None):
    user_text = f"Transcript:\n{transcript}"
    if feedback:
        user_text += f"\n\nYour previous answer was rejected: {feedback}. Return valid JSON only."
    resp = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        inferenceConfig={"maxTokens": 4000, "temperature": 0},
    )
    return resp["output"]["message"]["content"][0]["text"]


def _clean_nullable(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    value = value.strip()
    return None if value.lower() in NULL_WORDS else value


def parse_and_validate(raw):
    text = raw.strip()
    if text.startswith("```"):  # some models wrap JSON in code fences
        text = text.strip("`").removeprefix("json").strip()
    if not text.startswith("{") and "{" in text and "}" in text:  # text around the JSON
        text = text[text.index("{"): text.rindex("}") + 1]
    mom = json.loads(text)
    if not isinstance(mom, dict):
        raise ValueError("the answer must be a JSON object")
    if not isinstance(mom.get("summary"), str):
        raise ValueError("summary must be a string")
    decisions = mom.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(d, str) for d in decisions):
        raise ValueError("decisions must be a list of strings")
    items = mom.get("action_items")
    if not isinstance(items, list):
        raise ValueError("action_items must be a list")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each action item must be an object")
        if not isinstance(item.get("task"), str):
            raise ValueError("each action item needs a task string")
        for field in ("owner", "due_date"):
            if field not in item:
                raise ValueError(f"{field} is missing; use null when unknown")
            item[field] = _clean_nullable(item[field], field)
        item["due_date_quote"] = _clean_nullable(item.get("due_date_quote"), "due_date_quote")
    _validate_report_fields(mom)
    return mom


def _validate_report_fields(mom):
    """Fields used by the PDF. Missing ones get safe defaults; wrong types are errors (and trigger the retry)."""
    for field in ("title", "meeting_date", "mode", "client", "purpose"):
        mom[field] = _clean_nullable(mom.get(field), field)
    attendees = mom.get("attendees", [])
    if not isinstance(attendees, list):
        raise ValueError("attendees must be a list")
    for a in attendees:
        if not isinstance(a, dict) or not isinstance(a.get("name"), str) or not a["name"].strip():
            raise ValueError("each attendee must be an object with a name string")
        a["group"] = _clean_nullable(a.get("group"), "group")
    mom["attendees"] = attendees
    topics = mom.get("discussion_items", [])
    if not isinstance(topics, list):
        raise ValueError("discussion_items must be a list")
    for t in topics:
        if not isinstance(t, dict) or not isinstance(t.get("item"), str) or not isinstance(t.get("discussion"), str):
            raise ValueError("each discussion item needs item and discussion strings")
        t["status"] = _clean_nullable(t.get("status"), "status")
    mom["discussion_items"] = topics


_WEEKDAY_DATE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d+\w*",
    re.IGNORECASE,
)


def _norm(text):
    text = re.sub(r"\s+", " ", text.lower())
    text = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", text)  # 18th == 18
    return text.strip(" .,;")


def _in_transcript(date, haystack):
    # not followed by another digit/letter: "november 20" must not match inside "november 201"
    return re.search(re.escape(_norm(date)) + r"(?![0-9a-z])", haystack) is not None


_DATE_WORDS = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d",
    re.IGNORECASE,
)


_IMPLAUSIBLE_DAY = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{3,})\b",
    re.IGNORECASE,
)


def implausible_dates(mom):
    """Dates like 'November 201' (speech-to-text slip for 'twenty first'): shown as written, but flagged."""
    text = json.dumps(mom, ensure_ascii=False)
    return sorted({m.group(0) for m in _IMPLAUSIBLE_DAY.finditer(text)})


def dates_hidden_in_tasks(mom):
    """Action items whose task text contains a date while due_date is null (the model moved the date)."""
    return [i["task"] for i in mom["action_items"] if not i["due_date"] and _DATE_WORDS.search(i["task"])]


_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def ungrounded_dates(mom, transcript):
    """Dates in the MOM that do not appear word for word in the transcript.

    Checks every due_date and meeting_date, plus any 'Weekday, Month N' phrase anywhere in the
    MOM text. This is how a model 'fixing' a garbled date (e.g. 'November 201' -> '20th') is caught."""
    haystack = _norm(transcript)
    found = []
    if _DEVANAGARI.search(transcript):
        # Hindi/mixed transcript: the English date cannot match word for word, so the model must
        # quote the original words and the quote must appear in the transcript.
        return [i["due_date"] for i in mom["action_items"]
                if i["due_date"] and not (i.get("due_date_quote") and i["due_date_quote"] in transcript)]
    claimed = [i["due_date"] for i in mom["action_items"] if i["due_date"]]
    if mom.get("meeting_date"):
        claimed.append(mom["meeting_date"])
    text_fields = [mom.get("summary", ""), mom.get("purpose") or ""] + mom["decisions"]
    for t in mom.get("discussion_items", []):
        text_fields += [t["item"], t["discussion"], t.get("status") or ""]
    text_fields += [i["task"] for i in mom["action_items"]]
    for field in text_fields:
        claimed += _WEEKDAY_DATE.findall(field)
    for date in claimed:
        if not _in_transcript(date, haystack) and date not in found:
            found.append(date)
    return found


def _soft_problems(mom, transcript):
    """Problems that are retried once but never fail the workflow. Returns (feedback, warnings)."""
    feedback, warnings = [], []
    hindi = bool(_DEVANAGARI.search(transcript))
    for d in ungrounded_dates(mom, transcript):
        if hindi:
            feedback.append(f'the due date "{d}" needs due_date_quote: copy the exact original words of that '
                            "date from the transcript (they must appear there word for word)")
        else:
            feedback.append(f'the date "{d}" does not appear word for word in the transcript; '
                            "copy dates exactly as written there, even if they look wrong")
        warnings.append(f'Date "{d}" was not found in the transcript. Check it against the recording.')
    for task in dates_hidden_in_tasks(mom):
        feedback.append(f'the task "{task}" contains a date but due_date is null; move the date into due_date')
        warnings.append(f'Action "{task}" mentions a date but Due is empty. Check it.')
    for d in implausible_dates(mom):
        warnings.append(f'"{d}" is not a valid date (probably a speech-to-text error). Check the real date in the recording.')
    english_part = {k: v for k, v in mom.items() if k != "action_items"}
    english_part["action_items"] = [{k: v for k, v in i.items() if k != "due_date_quote"} for i in mom["action_items"]]
    if _DEVANAGARI.search(json.dumps(english_part, ensure_ascii=False)):  # due_date_quote is allowed to be Hindi
        feedback.append("the answer contains Hindi (Devanagari) text; write every field in English "
                        "and write names in Latin letters")
        warnings.append("Some text could not be translated to English. Check the PDF and the draft.")
    return "; ".join(feedback), warnings


def extract_with_retry(transcript):
    raw = ask_model(transcript)
    try:
        mom = parse_and_validate(raw)
        feedback, warnings = _soft_problems(mom, transcript)
        if not feedback:
            if warnings:  # nothing to retry, but the reader should still be told
                mom["warnings"] = warnings
            return mom
    except ValueError as err:  # JSONDecodeError is a ValueError
        feedback = str(err)
    raw = ask_model(transcript, feedback=feedback)
    mom = parse_and_validate(raw)  # a second structural failure raises and fails the workflow
    _, warnings = _soft_problems(mom, transcript)  # still wrong after the retry: keep it, flag it
    if warnings:
        mom["warnings"] = warnings
    return mom


def format_email(mom):
    lines = ["SUMMARY", mom["summary"], "", "DECISIONS"]
    lines += [f"- {d}" for d in mom["decisions"]] or ["- None"]
    lines += ["", "ACTION ITEMS"]
    for item in mom["action_items"]:
        owner = item["owner"] or "UNASSIGNED"
        due = item["due_date"] or "no date"
        lines.append(f"- {item['task']} | Owner: {owner} | Due: {due}")
    return "\n".join(lines)


def build_draft(mom, audio_name, pdf_url, pdf_uri):
    """Email draft the user copies into their mail client; the PDF is attached by hand."""
    title = mom.get("title") or audio_name
    when = f" held on {mom['meeting_date']}" if mom.get("meeting_date") else ""
    subject = f"MoM - {title}" + (f" - {mom['meeting_date']}" if mom.get("meeting_date") else "")
    body = [
        f"Subject: {subject}",
        "",
        "Hi all,",
        "",
        f"Please find attached the minutes of the meeting \"{title}\"{when}.",
        "",
        format_email(mom),
        "",
        "Please review the attached minutes and let me know if anything needs to be corrected.",
        "",
        "Regards,",
        mom.get("prepared_by") or "[Your name]",
    ]
    note = [
        "MOM DRAFT READY",
        f"1. Download the PDF and attach it to your email: {pdf_url}",
        "   (the link can expire after a few hours; the file stays in S3 at "
        f"{pdf_uri} - download it with: aws s3 cp {pdf_uri} .)",
        "2. Copy the draft below the line into your mail client.",
    ] + [f"CHECK BEFORE SENDING: {w}" for w in mom.get("warnings", [])] + [
        "",
        "----- EMAIL DRAFT (copy from here) -----",
    ]
    return "\n".join(note + body), "\n".join(body)


def handler(event, context):
    mom = extract_with_retry(load_transcript(event["transcriptKey"]))
    mom["prepared_by"] = PREPARED_BY or None
    audio_name = event["audioKey"].split("/")[-1]
    stem = event["transcriptKey"].split("/")[-1].removesuffix(".json")
    pdf_key, draft_key, json_key = f"mom/{stem}.pdf", f"mom/{stem}-draft.txt", f"mom/{stem}.json"

    s3.put_object(Bucket=BUCKET, Key=pdf_key, Body=build_pdf(mom), ContentType="application/pdf")
    s3.put_object(Bucket=BUCKET, Key=json_key, Body=json.dumps(mom, indent=2).encode(), ContentType="application/json")
    pdf_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": pdf_key}, ExpiresIn=LINK_SECONDS
    )
    email_body, draft_text = build_draft(mom, audio_name, pdf_url, f"s3://{BUCKET}/{pdf_key}")
    s3.put_object(Bucket=BUCKET, Key=draft_key, Body=draft_text.encode(), ContentType="text/plain")
    return {
        "audioKey": event["audioKey"],
        "mom": mom,
        "pdfKey": pdf_key,
        "draftKey": draft_key,
        "emailSubject": f"MOM draft ready: {audio_name}"[:100],
        "emailBody": email_body,
    }
