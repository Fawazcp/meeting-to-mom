import os
import re
import boto3

transcribe = boto3.client("transcribe")
BUCKET = os.environ["BUCKET"]
MAX_SPEAKERS = int(os.environ.get("MAX_SPEAKERS", "2"))
LANGUAGES = [c.strip() for c in os.environ.get("TRANSCRIBE_LANGUAGES", "en-US").split(",") if c.strip()]


def handler(event, context):
    key = event["detail"]["object"]["key"]  # e.g. uploads/acme-migration-call.mp3
    base = re.sub(r"[^0-9A-Za-z._-]", "-", key.split("/")[-1])
    job_name = f"mom-{base}-{context.aws_request_id[:8]}"  # unique per upload
    transcript_key = f"transcripts/{job_name}.json"

    # one language -> fixed code; several -> multi-language identification (e.g. Hindi + English in one call)
    if len(LANGUAGES) == 1:
        language = {"LanguageCode": LANGUAGES[0]}
    else:
        language = {"IdentifyMultipleLanguages": True, "LanguageOptions": LANGUAGES}

    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        **language,
        Media={"MediaFileUri": f"s3://{BUCKET}/{key}"},
        OutputBucketName=BUCKET,
        OutputKey=transcript_key,
        # speaker labels (spk_0, spk_1...) so "I will do X" can be tied to a speaker
        Settings={"ShowSpeakerLabels": True, "MaxSpeakerLabels": MAX_SPEAKERS},
    )
    return {"jobName": job_name, "transcriptKey": transcript_key, "audioKey": key}
