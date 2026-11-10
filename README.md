# meeting-to-mom

Upload a meeting recording to S3 and get a structured minutes-of-meeting (MOM) email.

Pipeline: S3 upload -> EventBridge -> Step Functions -> Amazon Transcribe -> Amazon Bedrock -> SNS email.

## Status

Reviewed and fixed locally; see TESTLOG.md for what has actually been run against AWS. Check every API call, IAM permission, model ID and the state machine syntax against the current AWS docs while you test.

## Prerequisites

- AWS account, AWS CLI v2 configured, AWS SAM CLI, Python 3
- Access to a Bedrock model in us-east-1 (the template defaults to `amazon.nova-lite-v1:0`; change `BedrockModelId` if needed)
- An email address to confirm the SNS subscription
- A budget alert in AWS Budgets, set before you deploy

## Local tests (no AWS calls)

```bash
python -m unittest discover -s tests
```

## Deploy

```bash
sam build
sam deploy --guided
```

Use region `us-east-1`. Then confirm the SNS subscription email BEFORE uploading; SNS does not deliver messages published to an unconfirmed email subscription.

For calls with more than two speakers, deploy with `--parameter-overrides MaxSpeakers=<n>`.

## Test

```bash
# 1. Generate a fake meeting with Amazon Polly (needs polly:SynthesizeSpeech)
python scripts/generate_meeting.py

# 2. Upload it
BUCKET=$(aws cloudformation describe-stacks --stack-name meeting-to-mom \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)
aws s3 cp acme-migration-call.mp3 "s3://$BUCKET/uploads/"
```

Open the newest execution in the Step Functions console and check the email.

## Answer key for the fake meeting

| Type | Item | Owner | Due |
| --- | --- | --- | --- |
| Decision | Blue-green cutover Saturday night, 11 p.m. to 2 a.m. | (decision, no owner) | Saturday, Nov 21 |
| Action | Rotate production database credentials | Daniel (named by the customer) | Wednesday, Nov 18 |
| Action | Send updated runbook and rollback checklist | Matthew (DevOps; says "I will") | Monday, Nov 16 |
| Action | Share cost estimate for both environments | Matthew (DevOps; says "I will") | Friday, Nov 20 |
| Action | Check that alerts cover the payment service | Nobody assigned | None |

The last row is deliberate: the pipeline must report "no owner" instead of inventing one.

## Clean up

```bash
aws s3 rm "s3://$BUCKET" --recursive
sam delete --stack-name meeting-to-mom
```

Then check for leftover CloudWatch log groups from the Lambdas.

## Hindi / Hinglish calls

`TranscribeLanguages` (default `hi-IN,en-IN`) turns on Amazon Transcribe multi-language identification, so a call that switches between Hindi and English is transcribed in both. Use a single code (for example `en-US`) for English-only calls. The MOM, PDF and email draft are always written in English.

Test audio: `python scripts/generate_meeting_hindi.py` makes a synthetic Hindi/English call with Amazon Polly (voices Arjun and Kajal). It has the same answer key as the English call above (same people, owners and dates, spoken in Hindi). Polly is synthetic speech, so a pass here does not prove the pipeline handles noisy real recordings.

Attendees: the PDF lists only people who spoke or were named in the recording and always adds a "confirm and add attendee details" row. Reading the real Teams attendance list needs the Microsoft Graph API and is not part of this pipeline.
