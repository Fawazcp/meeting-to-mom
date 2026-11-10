import boto3

transcribe = boto3.client("transcribe")


def handler(event, context):
    job = transcribe.get_transcription_job(
        TranscriptionJobName=event["jobName"]
    )["TranscriptionJob"]
    return {
        **event,
        "status": job["TranscriptionJobStatus"],
        "failureReason": job.get("FailureReason", "no reason reported"),
    }
