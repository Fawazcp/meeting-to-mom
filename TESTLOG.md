# TESTLOG

Every entry is a real command with real output. Costs come only from AWS billing / usage pages; "not available yet" means billing has not caught up.

## Run 0: starter files as delivered (local only, no AWS)
Time: 2026-11-10 (before 16:20 UTC)

```
$ python3 -m unittest discover -s tests
ModuleNotFoundError: No module named 'boto3'
Ran 1 test in 0.000s
FAILED (errors=1)
```
Cause: `extract_mom/app.py` creates boto3 clients at import and boto3 was not installed on the laptop (system Python 3.14.7). The README claimed the tests passed.
Fix: created a Python 3.12 venv (matches the Lambda runtime) with `aws-sam-cli`, `cfn-lint`, `boto3`.
Installed: SAM CLI 1.171.0, cfn-lint 1.58.0, AWS CLI 2.36.47, pandoc (brew).

```
$ .venv/bin/python -m unittest discover -s tests
Ran 8 tests in 0.000s
OK
```
The 8 starter tests passed on the unmodified code, but a review found cases they did not cover (see below).

## Review findings fixed before first deploy (found by reading code and AWS docs, not by an AWS run)
| # | Problem | Change |
|---|---|---|
| 1 | Transcript had no speaker labels, so "I will send the runbook" had no owner | `Settings={ShowSpeakerLabels, MaxSpeakerLabels}` in start_job; `build_transcript()` makes `spk_0: ...` lines; prompt rule: use a real name only if the speaker states it |
| 2 | Validator raised AttributeError/TypeError (no retry) on a JSON list or non-object items; accepted "null"/"None" strings as owner | All shape errors are ValueError; null-like strings normalised to null; decisions must be strings; text around JSON is stripped |
| 3 | Wait/Check loop could run forever | `TimeoutSeconds: 1800` on the state machine |
| 4 | No Retry on Start/Check; ExtractMom Retry missing `Lambda.AWSLambdaException`, `Lambda.SdkClientException` | Added; boto3 standard retries (5) on the Bedrock client |
| 5 | FAILED transcription lost its reason | check_job returns `failureReason`; Fail state uses `CausePath` |
| 6 | Transcribe IAM was `Resource: "*"` | Scoped to `transcription-job/mom-*` |
| 7 | Lambda log groups survive `sam delete` | Explicit log groups with 14-day retention, attached via `LoggingConfig` |
| 8 | No email validation | `AllowedPattern` on the parameter |
| 9 | Fake call had no self-introductions, so speaker names were unknowable | Two intro lines added to scripts/generate_meeting.py; README answer key updated |

Docs checked: Nova Lite model ID `amazon.nova-lite-v1:0` supports Converse in us-east-1 (docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html); Transcribe `Settings.ShowSpeakerLabels/MaxSpeakerLabels`, output labels `spk_0..` (transcribe/latest/dg/diarization.html); Polly neural voices Joanna and Matthew exist for en-US (polly/latest/dg/neural-voices.html).
Still unverified until a real run: whether Transcribe also needs `s3:ListBucket` on the caller, and the exact location of `speaker_labels` in the output JSON (code reads `results.speaker_labels`).

## Run 1: pre-deploy checks (local)
Time: 2026-11-10T16:20Z

```
$ .venv/bin/python -m unittest discover -s tests
Ran 17 tests in 0.000s
OK
$ .venv/bin/cfn-lint template.yaml        -> no findings
$ .venv/bin/sam validate --lint           -> template.yaml is a valid SAM Template
$ .venv/bin/sam build                     -> Built Template : .aws-sam/build/template.yaml
```

## Run 2: AWS credentials check (read-only)
Time: 2026-11-10T16:20Z

```
$ aws sts get-caller-identity
aws: [ERROR]: An error occurred (InvalidClientTokenId) when calling the GetCallerIdentity operation: The security token included in the request is invalid.
$ aws bedrock list-foundation-models --region us-east-1 ...
aws: [ERROR]: An error occurred (UnrecognizedClientException) when calling the ListFoundationModels operation: The security token included in the request is invalid.
```
Cause: the default profile holds expired/invalid credentials. Fix: user logs in with `aws login --profile <your-profile>`; later commands use `--profile <your-profile>`.
Cost: nothing deployed yet.

## Run 3: credentials and Bedrock access check (read-only)
Time: 2026-11-10T16:24Z, profile `<your-profile>`, region us-east-1

```
$ aws sts get-caller-identity --profile <your-profile>        -> arn:aws:iam::<account>:user/<name>
$ aws bedrock list-foundation-models ... amazon.nova-lite-v1:0
  ACTIVE, inferenceTypesSupported: ON_DEMAND, INFERENCE_PROFILE
$ aws bedrock get-foundation-model-availability --model-id amazon.nova-lite-v1:0
  agreementAvailability AVAILABLE, authorizationStatus AUTHORIZED, entitlementAvailability AVAILABLE, regionAvailability AVAILABLE
$ aws budgets describe-budgets
  My Monthly Cost Budget, My Zero-Spend Budget
```
Result: credentials work, Nova Lite is authorized and supports on-demand in us-east-1, so no console change is needed. Budget alerts already exist in the account.

## Run 4: deploy
Time: 2026-11-10T16:25:33Z to 16:29:31Z
Budget alert: user chose existing "My Monthly Cost Budget".

```
$ sam deploy --stack-name meeting-to-mom --region us-east-1 --profile <your-profile> --resolve-s3 --capabilities CAPABILITY_IAM --no-confirm-changeset --parameter-overrides NotificationEmail=<user email>
... CREATE_COMPLETE AWS::CloudFormation::Stack meeting-to-mom
Outputs: BucketName = meeting-to-mom-audiobucket-<suffix>
Successfully created/updated stack - meeting-to-mom in us-east-1
```
Errors: none. Waiting for the user to confirm the SNS subscription email.
Cost: not available yet.

## Run 5: generate test audio, check SNS subscription
Time: 2026-11-10T16:31:43Z

```
$ AWS_PROFILE=<your-profile> python scripts/generate_meeting.py   -> no errors
acme-migration-call.mp3: 478740 bytes, MPEG layer III, 24 kHz mono
$ aws sns get-topic-attributes ... SubscriptionsConfirmed / SubscriptionsPending
0	1
```
Result: Polly audio generated. SNS still reports the subscription as PendingConfirmation (0 confirmed, 1 pending), although the user said they confirmed. Upload held back so the result email is not dropped.

## Run 6: SNS subscription re-check
Time: 2026-11-10T16:33:41Z
```
$ aws sns get-topic-attributes ... SubscriptionsConfirmed / SubscriptionsPending
1	0
```
Result: subscription confirmed after the user clicked the link a second time (the first attempt had not registered).

## Run 7: first end-to-end test with Polly audio
Time: upload 2026-11-10T16:34:07Z; execution 22:04:12 to 22:05:17 IST (16:34:12 to 16:35:17Z), status SUCCEEDED, no errors, no retries.

```
$ aws s3 cp acme-migration-call.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/ --profile <your-profile>
upload: ./acme-migration-call.mp3 to s3://.../uploads/acme-migration-call.mp3
```
Execution history: 6 Task, 3 Wait, 3 Choice states entered (3 polls of the transcription job).
Bucket after the run: `uploads/acme-migration-call.mp3` (478740 B), `transcripts/mom-acme-migration-call.mp3-03eab57e.json` (60221 B), `transcripts/.write_access_check_file.temp` (0 B, written by Transcribe). No loop: the transcript write did not start a second execution.
Open questions from earlier, now answered: Transcribe worked with only GetObject on uploads/* and PutObject on transcripts/* (no s3:ListBucket needed); `speaker_labels` is at `results.speaker_labels`, `speakers: 2`.
Audio length: 79.319 s (not 2 minutes; the script text is shorter than the spec's "2-minute call").

### Email text sent to SNS (SendMom input, from the execution history)
```
Subject: MOM: acme-migration-call.mp3
SUMMARY
The meeting discussed the migration plan for Acme Retail's staging environment, focusing on minimizing downtime. The team agreed on a cutover on Saturday, November 20th, between 11 p.m. and 2:00 a.m., using a blue-green deployment strategy. Action items include rotating production database credentials by November 18th and reviewing monitoring dashboards for the payment service.

DECISIONS
- Cutover on Saturday, November 20th, between 11 p.m. and 2:00 a.m.
- Use a blue-green deployment strategy

ACTION ITEMS
- Rotate production database credentials | Owner: Daniel | Due: November 18th
- Review monitoring dashboards for payment service coverage | Owner: UNASSIGNED | Due: no date
- Send updated runbook and rollback checklist | Owner: Matthew | Due: November 16th
- Prepare and share cost estimate for running both environments in parallel | Owner: Matthew | Due: November 20th
```
(That the real inbox email matches this text: waiting for the user to confirm.)

### Comparison with the README answer key
| Item | Result |
|---|---|
| Decision: blue-green deployment | correct |
| Decision: cutover Saturday night, 11 p.m. to 2 a.m. | correct |
| Decision date: Saturday, Nov 21 | WRONG: email says "Saturday, November 20th" |
| Rotate credentials, Daniel, Wed Nov 18 | correct (weekday "Wednesday" dropped, date kept) |
| Runbook + rollback checklist, Matthew, Mon Nov 16 | correct (weekday dropped) |
| Cost estimate, Matthew, Fri Nov 20 | correct (weekday dropped) |
| Alerts for payment service: no owner, no date | correct (UNASSIGNED, no date), nothing invented |

### What went wrong, with cause (verified from the transcript JSON)
1. Transcribe wrote "The cutover window is Saturday, November 201." for the spoken "November twenty first". The model turned the garbled "201" into "20th", so the email shows a date that was never said and that is also a Friday, not a Saturday. The prompt said "copy dates as spoken" but the model silently repaired the text. This is a real defect of the current pipeline, not fixed yet.
2. Speaker label slip: the first greeting was split across speakers ("spk_0: Hi, this is Matthew from the DevOps team. Hi" / "spk_1: Matthew, this is Priya from Acme Retail."). It did not change the result here (owners Matthew and Daniel were correct).

### Usage (real numbers)
- Bedrock `amazon.nova-lite-v1:0`, CloudWatch AWS/Bedrock, 16:30-17:30Z: Invocations 1, InputTokenCount 620, OutputTokenCount 269 (so no JSON retry was needed).
- extract_mom Lambda REPORT: Duration 1310.60 ms, Billed Duration 1813 ms, Memory 512 MB, Max used 93 MB, Init 501.86 ms.
- Transcribe job: audio 79.319 s, created 22:04:13.8 IST, completed 22:04:59.3 IST. Settings ShowSpeakerLabels true, MaxSpeakerLabels 2.
- Polly: 1314 characters synthesized (neural voices).
- Dollar cost shown in AWS billing: not available yet.

## Run 8: PDF + email draft feature (local only, not deployed yet)
Time: 2026-11-10T16:58Z
Request: the user's organisation sends MOMs as an email draft with a PDF attachment in their company layout (document-control header table, attendees, purpose, key outcomes, discussion by item, action items with owner/due). Reference layout: the user's own earlier MOM PDF (3 pages; client content is NOT copied into this repo, tests or article). Delivery chosen by the user: PDF in S3 + presigned link in the SNS email (SNS cannot attach files); draft text in the email body and as a file in S3.

Changes: new `src/extract_mom/mom_pdf.py` (fpdf2 2.9.0, `requirements.txt`), JSON shape extended (title, meeting_date, mode, client, purpose, attendees, discussion_items; existing summary/decisions/action_items unchanged), `build_draft()`, handler writes `mom/<name>.pdf`, `.json`, `-draft.txt` and returns a presigned link; template: `s3:PutObject/GetObject` on `mom/*`, `PreparedBy` parameter, Lambda timeout 120 s, maxTokens 4000.

### Error found while testing
```
$ python -m unittest discover -s tests
botocore.exceptions.ClientError: An error occurred (InvalidAccessKeyId) when calling the PutObject operation: The AWS Access Key Id you provided does not exist in our records.
```
Cause: my new handler test did not replace the S3 client, so the "local" test made a real PutObject call with the (invalid) default-profile credentials. Nothing was created. Fix: the test now uses a fake S3 object. Rule kept: unit tests never call AWS.
Also fixed: 5 older tests compared the validator output to the exact input dict; the validator now adds default report fields, so they compare to `GOOD_NORMALISED`.

### Packaging check
`sam build` with fpdf2 fetched Linux wheels (Pillow `_imaging*.cpython-312-x86_64-linux-gnu.so`), so it runs on the x86_64 Lambda although built on macOS (no Docker needed).

### Docs finding (presigned URL lifetime)
AWS docs: a URL signed with IAM role credentials expires when the role session expires, even if a longer time is requested (docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html). The code requests 6 hours; the email also gives the S3 path and an `aws s3 cp` command. The real expiry will be measured after deploy.

### Local checks
```
python -m unittest discover -s tests  -> Ran 18 tests, OK
cfn-lint template.yaml                -> no findings
sam validate --lint                   -> valid
sam build                             -> Build Succeeded
```
Sample PDF rendered locally from fake Acme data and visually compared with the user's template layout; table borders were too heavy and were thinned.
Cost: nothing deployed in this run.

## Run 9: date fix and deploy of the PDF/draft version
Time: 2026-11-10T16:59:14Z (check), deploy 16:59:30Z to 17:00:44Z

Date fix (answers the "November 201" -> "20th" defect from Run 7):
- Prompt: copy dates and numbers EXACTLY as written, even if garbled; never correct them.
- Code: `ungrounded_dates()` checks every due_date, meeting_date and every "Weekday, Month N" phrase in the MOM text against the transcript. A miss triggers the one retry with the offending dates in the error message. If still not in the transcript after the retry, the MOM is kept and "CHECK BEFORE SENDING: Date ... was not found in the transcript" is added to the email note (not a hard failure, so a speech-to-text glitch does not block the MOM).
- Offline check against the real Run 7 transcript and the real wrong output: flagged exactly `['Saturday, November 20th']`; the legitimate due dates (November 18th, November 20th for the cost estimate) were not flagged.
- Unit tests: 23 tests, OK. cfn-lint clean, sam validate valid, sam build succeeded.

```
$ sam deploy --stack-name meeting-to-mom --region us-east-1 --profile <your-profile> --resolve-s3 --capabilities CAPABILITY_IAM --no-confirm-changeset --parameter-overrides NotificationEmail=<user email> PreparedBy="Asha K R"
UPDATE_COMPLETE AWS::IAM::Role ExtractMomFunctionRole
UPDATE_COMPLETE AWS::Lambda::Function ExtractMomFunction
UPDATE_COMPLETE AWS::CloudFormation::Stack meeting-to-mom
Successfully created/updated stack - meeting-to-mom in us-east-1
```
Errors: none. Only the extract Lambda and its role changed. Cost: not available yet.

## Run 10: second end-to-end test (same audio, PDF + draft version)
Time: upload 2026-11-10T17:01:27Z; execution 22:31:31 to 22:31:58 IST (27 s), status SUCCEEDED, no errors.
```
$ aws s3 cp acme-migration-call.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-run2.mp3 --profile <your-profile>
```
Created in S3: `mom/mom-acme-migration-call-run2.mp3-40778273.pdf` (2969 B), `.json` (2094 B), `-draft.txt` (1141 B). The SNS email carried the draft and a presigned link. PDF layout rendered correctly (header table, attendees, purpose, key outcomes, discussion table, action table).
Usage: Bedrock Invocations 1 (no retry), InputTokenCount 836, OutputTokenCount 492; extract_mom REPORT: Duration 2421.90 ms, Billed Duration 4212 ms, Max Memory 131 MB, Init 1789.53 ms. Cost: not available yet.

### Comparison with the answer key (README) - three things went wrong
| Item | Result |
|---|---|
| Decision: blue-green, quick rollback | correct |
| Decision date: Saturday, Nov 21 | WRONG again: "Saturday, November 20" (transcript says "November 201") |
| Rotate credentials, Daniel, Wed Nov 18 | owner correct; date only inside the task text, Due = "No date stated" (WRONG: due_date null) |
| Send runbook + rollback checklist, Matthew, Mon Nov 16 | MISSING (the model dropped this action item entirely) |
| Cost estimate, Matthew, Fri Nov 20 | owner correct; date only inside task text, Due = "No date stated" (WRONG) |
| Alerts for payment service: no owner, no date | correct (Unassigned, no date); nothing invented |
Not invented: no owner or date that was not said; the wrong date comes from the transcript's "201".

### Defects found and causes
1. **Signature/"Prepared by" says "Asha", expected "Asha K R".** Cause: `aws lambda get-function-configuration` shows `PREPARED_BY=Asha`. `sam deploy --parameter-overrides PreparedBy="Asha K R"` was split at the spaces by SAM and "C P" was dropped silently. Fix: pass the value with literal quotes (`'PreparedBy="Asha K R"'`) and verify the Lambda variable after deploy.
2. **The new date guard did not fire.** Cause: it checked `"saturday, november 20" in transcript`, which is true because the transcript has "november 201". Fix: match with a not-followed-by-digit/letter boundary and ignore st/nd/rd/th suffixes; added 4 unit tests (one reproduces this exact case).
3. **due_date null with the date in the task text; runbook item dropped.** Cause: with the larger JSON shape Nova Lite stopped filling `due_date` and skipped one commitment (Run 1, with the small shape, had all four items and due dates). Fixes so far: prompt rules (go through the transcript turn by turn, include every commitment, put dates only in due_date) and a new soft check `dates_hidden_in_tasks()` that triggers the one retry and, if still wrong, adds a CHECK BEFORE SENDING line. Replaying the real Run 10 output through the new checks flags the wrong date and both hidden dates. A dropped action item cannot be detected by code; if the retest still drops items, the next step is a stronger model (`BedrockModelId=amazon.nova-pro-v1:0`).
Local: 27 unit tests OK, cfn-lint clean, sam build succeeded. Not deployed yet.

## Run 11: third end-to-end test (fixes deployed)
Time: deploy 2026-11-10T17:06:08Z; upload 17:07:23Z; execution 22:37:29 to 22:37:57 IST (28 s), SUCCEEDED, no errors.
```
$ sam deploy --stack-name meeting-to-mom ... --parameter-overrides NotificationEmail=<user email> 'PreparedBy="Asha K R"'   -> UPDATE_COMPLETE
$ aws lambda get-function-configuration ... PREPARED_BY  -> [Asha K R]      (fix for the Run 10 signature defect confirmed)
$ aws s3 cp acme-migration-call.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-run3.mp3 --profile <your-profile>
```
Usage: Bedrock (CloudWatch AWS/Bedrock, 17:05-18:05Z) Invocations 2, InputTokenCount 1881, OutputTokenCount 988 -> the retry fired once, i.e. the new date/due-date guard rejected the first answer and the second answer was accepted. (Which of the two problems triggered it was not logged by the Lambda; the Lambda does not log the feedback text.) extract_mom REPORT: Duration 4136.69 ms, Billed 5911 ms, Max Memory 131 MB, Init 1773.60 ms. Cost: not available yet.

### Email text (from the execution history), compared with the answer key
```
Subject: MoM - Acme Retail Staging Environment Migration ... Regards, Asha K R
DECISIONS
- Cutover on Saturday night between 11 p.m. and 2:00 a.m.
- Use a blue-green deployment strategy
ACTION ITEMS
- Rotate production database credentials | Owner: Daniel | Due: Wednesday, November 18th
- Review monitoring dashboards to check if alerts cover the payment service | Owner: UNASSIGNED | Due: no date
- Prepare and share cost estimate for running both environments in parallel | Owner: Matthew | Due: Friday, November 20th
- Send updated runbook and rollback checklist | Owner: Matthew | Due: Monday, November 16th
```
| Item | Result |
|---|---|
| Decision: blue-green | correct |
| Decision: cutover Saturday night 11 p.m. to 2 a.m. | correct |
| Decision date Saturday, Nov 21 | MISSING (not wrong): after the retry the model left the date out, because the transcript only says "November 201". No false date is shown. No warning line was added. |
| Rotate credentials, Daniel, Wed Nov 18 | correct |
| Runbook + rollback checklist, Matthew, Mon Nov 16 | correct (was missing in Run 10) |
| Cost estimate, Matthew, Fri Nov 20 | correct |
| Alerts for payment service: no owner, no date | correct (UNASSIGNED, no date); nothing invented |
Invented content: none found. Remaining weaknesses (from the saved JSON): attendees list has Matthew and Priya but not Daniel, who is named in the call but never speaks; discussion table has 3 rows and omits the runbook item and the cutover topic; `status` is empty for all rows; meeting_date and mode are null ("To be confirmed" in the PDF), which is correct because the call states neither.

### Presigned link check
URL in the SNS email: `X-Amz-Expires=21600` (6 h), signed 17:07:57Z. Fetched at 17:08:48Z with curl: HTTP 200, 3721 bytes, application/pdf, file starts with `%PDF-1.3`. Whether it really lives 6 h (role-credential limit) is not measured yet.
Not yet checked: that the email in the user's inbox matches the SNS text above (waiting for the user).

## Run 12: Hindi / Hinglish support (local only, not deployed yet)
Time: 2026-11-10T17:17Z
Request: client calls are in Hindi; the MOM must be English; question how attendees are identified.

Docs checked: Transcribe supports `hi-IN` (batch; numbers, acronyms) and multi-language identification handles Hindi + English in one file (transcribe/latest/dg/lang-id-batch.html, supported-languages.html); Transcribe does not translate; Nova models are described as trained on 200+ languages (nova/latest/userguide/what-is-nova.html). Not documented / unknown until tested: speaker labels together with multi-language identification, and Nova Lite quality for Hindi.
Polly check (read-only): `aws polly describe-voices --language-code en-IN --include-additional-language-codes` -> Arjun (male, generative, hi-IN), Kajal (female, generative+neural, hi-IN), Aditi, Kiara.

Changes: `TranscribeLanguages` parameter (default hi-IN,en-IN; start_job uses IdentifyMultipleLanguages when more than one code); prompt writes all output in English with Latin-letter names; new `due_date_quote` field and a Hindi date check (the English date is accepted only if the quoted original words appear in the transcript; the strict word-for-word check remains for English transcripts); retry + warning if Devanagari text is left in the output (the PDF font cannot draw it); PDF attendees table now says names are only those spoken/named and adds a "To be added: confirm and add attendee details" row. Attendance fetching from Teams is not implemented (needs Microsoft Graph, app registration and admin consent).
Test audio: `scripts/generate_meeting_hindi.py` -> acme-migration-call-hindi.mp3, 507684 bytes, 1181 Polly characters (Arjun generative + Kajal neural, hi-IN). Synthetic speech, not a real recording.
Local checks: 35 unit tests OK (new: Hindi date checks, Devanagari feedback, start_job language settings), cfn-lint clean, sam validate valid, sam build succeeded.
Not deployed. Cost: not available yet.

## Run 13: deploy of the Hindi build, then Hindi test (synthetic Hinglish call)
Time: deploy 2026-11-10T17:18:38Z (UPDATE_COMPLETE for StartJobFunction, ExtractMomFunction; no errors). Lambda variables checked: TRANSCRIBE_LANGUAGES=hi-IN,en-IN, MAX_SPEAKERS=2, PREPARED_BY=Asha K R, MODEL_ID=amazon.nova-lite-v1:0.
Upload 17:20:01Z, execution 22:50:06 to 22:50:36 IST, SUCCEEDED, no errors.
```
$ aws s3 cp acme-migration-call-hindi.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-hindi.mp3 --profile <your-profile>
```
Transcribe (from the transcript JSON): `language_codes: hi-IN, 83.45 s`; `speakers: 2`. So speaker labels DO work together with multi-language identification. The transcript is Devanagari with dates as digits ("शनिवार 21 नवम्बर", "बुधवार 18 नवम्बर", "सोमवार 16 नवम्बर", "शुक्रवार 20 नवम्बर").
Transcribe errors: "Acme Retail" written as "एएम रिटेल" ("AM Retail"), "DevOps" as "डॉप" ("Dop"), "business hours" as "बिजनेस हॉर्स", "प्रिया" as "प्रियया"; a few turn boundaries are cut mid-sentence ("... कर सकती" / "है? हाँ ...").
Bedrock (CloudWatch, 22:50 IST minute): Invocations 2 (a retry fired), InputTokenCount 2285, OutputTokenCount 1082. Cost: not available yet.

### Email (from execution history) compared with the answer key
| Item | Result |
|---|---|
| Decision blue-green | correct |
| Decision cutover Saturday night 11 p.m. to 2 a.m., Sat Nov 21 | correct ("Saturday, 21st November"); this time the transcript had a clean "21" |
| Rotate credentials, Daniel, Wed Nov 18 | correct, quote "बुधवार 18 नवम्बर" valid |
| Runbook + rollback checklist, Arjun, Mon Nov 16 | correct (owner named from his self-introduction), but due_date_quote empty -> warning |
| Cost estimate, Arjun, Fri Nov 20 | correct owner/date, quote empty -> warning |
| Alerts for payment service: no owner, no date | MISSING from action items (dropped by the model) |
Invented / wrong: a decision line "Monitoring dashboard checks and cost estimation will be discussed in the next meeting" is wrong for the cost estimate (it was assigned to Arjun); the client appears as "AM Retail" and the team as "Dop Team" (inherited from the speech-to-text output, not invented by the model); title was null so the subject used the file name.

### Defects found and causes
1. False warning "Some text could not be translated to English". Cause: my Devanagari check scanned the whole MOM including `due_date_quote`, which is Hindi on purpose. Fix: exclude due_date_quote from that check (unit test added).
2. Two dates flagged for missing quotes. Cause: the model left `due_date_quote` null; the retry message only said the date was "not found word for word", which does not tell the model what to do in Hindi mode. Fix: the Hindi feedback now asks for `due_date_quote` explicitly and the prompt marks it REQUIRED for Hindi/mixed transcripts.
3. Dropped unassigned item and a wrong decision line: Nova Lite quality (see also Run 10). Candidate fix: stronger model (`BedrockModelId=amazon.nova-pro-v1:0`).

## Run 14: English regression test with the multi-language build
Time: upload 2026-11-10T17:21:56Z; execution 22:52:01 to 22:52:25 IST (24 s), SUCCEEDED, no errors.
```
$ aws s3 cp acme-migration-call.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-run4-en.mp3 --profile <your-profile>
```
Transcribe: multi-language mode picked `en-IN` for 78.35 s of the English audio, 2 speakers; the transcript still contains "November 201" for "twenty first".
Bedrock (22:52 IST minute): Invocations 1, InputTokenCount 1019, OutputTokenCount 518. Cost: not available yet.
Email vs answer key: blue-green correct; cutover Saturday night 11 p.m. to 2 a.m. correct; cutover DATE omitted (no false date; "201" is garbled in the transcript); credentials Daniel Wed Nov 18 correct; cost estimate Matthew Fri Nov 20 correct; payment alerts UNASSIGNED / no date correct; runbook + rollback checklist, Matthew, Mon Nov 16: MISSING (dropped by the model). No invented content found. No warning lines.
Conclusion: the multi-language setting did not break English; Nova Lite randomly drops one action item per run (Run 10: runbook, Run 13: alerts, Run 14: runbook).

## Pre-deploy checks for the next build (local)
37 unit tests OK, sam build succeeded. Nova Pro availability (read-only): `get-foundation-model-availability amazon.nova-pro-v1:0` -> AUTHORIZED, entitlement AVAILABLE, region AVAILABLE; list-foundation-models: ACTIVE, ON_DEMAND + INFERENCE_PROFILE.

## Run 15: Nova Pro (`amazon.nova-pro-v1:0`) with the Hindi build
Time: deploy 2026-11-10T17:23:39Z (UPDATE_COMPLETE for ExtractMomFunctionRole and ExtractMomFunction; MODEL_ID=amazon.nova-pro-v1:0 and PREPARED_BY=Asha K R verified on the Lambda). No errors.
```
$ sam deploy ... --parameter-overrides NotificationEmail=<user email> 'PreparedBy="Asha K R"' BedrockModelId=amazon.nova-pro-v1:0
$ aws s3 cp acme-migration-call-hindi.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-hindi-pro.mp3 --profile <your-profile>   (17:25:44Z)
$ aws s3 cp acme-migration-call.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-pro-en.mp3 --profile <your-profile>         (17:26:22Z)
```
Both executions SUCCEEDED, no errors: Hindi 22:55:49 to 22:56:17 IST (28 s), English 22:56:26 to 22:56:52 IST (26 s). Neither had a CHECK BEFORE SENDING warning.
Usage (both runs fall in the same CloudWatch minute, 22:56 IST, so the numbers are the TOTAL for the two runs): Bedrock `amazon.nova-pro-v1:0` Invocations 2 (so no retry), InputTokenCount 2143, OutputTokenCount 1262. Lambda REPORT lines for extract_mom in that window: billed 7848 ms (with 1822.83 ms init), 3180 ms, 7255 ms (init 1828.96 ms), 4682 ms; which line belongs to which run is not shown by the log, so I do not assign them. Cost: not available yet.

### Hindi call, Nova Pro, compared with the answer key
| Item | Result |
|---|---|
| Blue-green decision | correct |
| Cutover Saturday night 11 p.m. to 2 a.m., Saturday 21 November | correct ("between 11 PM and 2 AM on Saturday, 21st November") |
| Rotate credentials, Daniel, Wed Nov 18 | correct |
| Runbook + rollback checklist, Arjun, Mon Nov 16 | correct (due-date quotes now filled, no warning) |
| Cost estimate, Arjun, Fri Nov 20 | correct |
| Alerts for payment service: no owner, no date | MISSING from the action items (the discussion table has 4 rows; the open item is not listed as an action) |
Not invented: no wrong owner or date. Cost estimate wrongly "to be discussed next meeting" (Nova Lite error in Run 13) is gone. The model wrote a title ("Migration plan discussion for AM Retail's staging environment"). "AM Retail" and "DOP Team" still come from Transcribe's Hindi transcript.

### English call, Nova Pro, compared with the answer key
All four action items present with correct owners and dates (Daniel Nov 18, Matthew Nov 16, Matthew Nov 20) plus the payment-alerts item as UNASSIGNED / no date; blue-green and cutover window correct. Defect: a decision line says "The cutover window is officially set for Saturday, November 201." The model copied the speech-to-text slip verbatim (as the prompt demands), so the guard did not flag it. It does not invent a date, but it is visibly wrong and gave no warning.
Fix (local, not deployed): `implausible_dates()` adds a CHECK BEFORE SENDING line when a month is followed by a number of 3+ digits. Found while fixing: warnings were dropped when the first answer needed no retry; fixed and covered by a test.

### Model comparison from real runs (same two audio files)
| | Nova Lite | Nova Pro |
|---|---|---|
| English call | dropped the runbook item in Runs 10 and 14; all items in Run 11 | all 4 items + the unassigned one |
| Hindi call | dropped the alerts item, wrote a wrong decision line, 2 date-quote warnings | dropped the alerts item, no wrong lines, no warnings |
Only one run per model and call was made for Run 13/14/15 (Run 11 and 10 were English), so this is an observation from few samples, not a benchmark.
Next local change (not deployed): prompt rule with a concrete example of an unassigned open task ("somebody should check ...") so it is never dropped. Local checks: 39 unit tests OK, cfn-lint clean, sam build succeeded.

## Run 16: Hindi call again, Nova Pro, with the unassigned-task rule and implausible-date warning
Time: deploy 2026-11-10T17:28:54Z (UPDATE_COMPLETE for ExtractMomFunction; MODEL_ID=amazon.nova-pro-v1:0, PREPARED_BY=Asha K R verified). Upload 17:29:50Z; execution 22:59:54 to 23:00:22 IST (28 s), SUCCEEDED, no errors, no warnings.
```
$ sam deploy ... BedrockModelId=amazon.nova-pro-v1:0
$ aws s3 cp acme-migration-call-hindi.mp3 s3://meeting-to-mom-audiobucket-<suffix>/uploads/acme-migration-call-hindi-pro2.mp3 --profile <your-profile>
```
Usage (single run, so exact): Bedrock `amazon.nova-pro-v1:0` Invocations 1 (no retry), InputTokenCount 1174, OutputTokenCount 594. Cost: not available yet.
S3 `mom/`: `.pdf` 3918 B, `.json` 2587 B, `-draft.txt` 1129 B. The PDF (downloaded and read) has the layout, "Prepared by Asha K R", the attendee table with the extra row "To be added: Attendance is not captured by this tool. Confirm and add the full attendee list.", and the action table runs onto page 2 with the header row repeated.

### Comparison with the answer key (Hindi call)
| Item | Result |
|---|---|
| Blue-green decision | correct |
| Cutover Saturday night 11 p.m. to 2 a.m., Saturday 21 November | correct |
| Rotate credentials, Daniel, Wed 18 Nov | correct |
| Runbook + rollback checklist, Arjun, Mon 16 Nov | correct |
| Cost estimate, Arjun, Fri 20 Nov | correct |
| Alerts for payment service: no owner, no date | correct ("Check whether the alerts cover the payment service | UNASSIGNED | no date"): this item was missing in Run 13 and Run 15 |
Invented content: none. Remaining issues, all from speech-to-text on the Hindi audio and not from the model: client written "AM Retail" (spoken "Acme Retail"), team "Dop Team" (spoken "DevOps"); Daniel is listed under the customer group because the customer said "my colleague Daniel" (correct for this call). Meeting date/time and mode are "To be confirmed" because the call states neither.
This is one run; the item-drop problem was random in earlier runs, so a single pass is not proof that it cannot recur.

## Run 17: user confirmation and usage / cost collection
Time: 2026-11-10T17:35Z to 17:38Z
User confirmation (their words, "1- yes"): the emails received in the inbox match the text recorded in this log and the downloaded PDF opens properly. User decision: do not clean up now (the stack stays for tests with real Hindi and English recordings, which the user will run later); write the article next.

### Usage totals measured from AWS (2026-11-10 UTC day)
- Step Functions executions: 8, all SUCCEEDED (`aws stepfunctions list-executions`).
- Transcribe: 8 transcripts in S3. Audio length from `results.audio_segments` (last end_time): English call 79.319 s x 5 jobs, Hindi call 84.15 s x 3 jobs, total 649.045 s. (Transcribe's own `language_codes` duration for the Hindi job was 83.45 s; the billed duration is not visible to me.)
- Bedrock (CloudWatch AWS/Bedrock, whole day): `amazon.nova-lite-v1:0` Invocations 7, InputTokenCount 6641, OutputTokenCount 3349; `amazon.nova-pro-v1:0` Invocations 3, InputTokenCount 3317, OutputTokenCount 1856.
- Polly: English script 1314 characters (neural) generated once (Run 5); Hindi script 1181 characters (generative Arjun + neural Kajal) generated once (Run 12). Characters counted from the script text.
- extract_mom Lambda billed duration examples: 1813 ms (Run 1), 4212 ms (Run 10), 5911 ms (Run 11).

### Billing
```
$ aws ce get-cost-and-usage --time-period Start=2026-11-10,End=2026-11-11 --granularity DAILY --metrics UnblendedCost UsageQuantity --group-by Type=DIMENSION,Key=SERVICE   (17:38Z)
Estimated: true. Services returned: AWS Glue 0, AWS Key Management Service -0.0000000132, AWS Secrets Manager -0.000000004, Amazon CloudFront 0, Amazon DynamoDB 0, EC2 - Other -0.0000000005, Amazon Simple Storage Service 0, AmazonCloudWatch 0.
```
No line for Transcribe, Bedrock, Polly, Lambda or Step Functions yet. Billed cost: not available yet. (Cost Explorer API requests are charged by AWS; one request was made.)

### Prices looked up in the AWS docs (used only for the labelled arithmetic in the article)
- Transcribe batch: $0.006 per minute in US East (N. Virginia), from the pricing page example (aws.amazon.com/transcribe/pricing); docs say usage is charged in 1-second increments with no minimum (docs.aws.amazon.com/transcribe/latest/dg/what-is.html).
- Nova per 1,000 tokens (input / output): Lite $0.00006 / $0.00024, Pro $0.0008 / $0.0032. Source: AWS ML blog "Effective cost optimization strategies for Amazon Bedrock", prices "current as of May 21, 2025" for US East (Ohio); not confirmed for us-east-1 today.
- Polly, Lambda, Step Functions, S3 prices: not looked up.

## Run 18: article
Time: 2026-11-10 (after 17:38Z)
`article.md` written (about 1,670 lines) with the code blocks inserted programmatically from the project files and the two sample emails taken from the real execution histories (Run 15 English, Run 16 Hindi); links and bucket name replaced by `<URL>` / `<your-bucket>`, the user's name replaced by a placeholder name in the article. Four screenshot TODO markers (S3 upload, Step Functions graph, MOM email, optional PDF page).
Doc claims checked while writing: SNS "Email" transport sends regular text-based messages (SNS FAQ); SES sandbox only sends to verified addresses and senders must be verified (SES docs). Wording about SNS was softened to "I did not find a way to attach a file".
```
$ brew install typst   -> typst 0.15.1
$ pandoc article.md -o article.pdf --pdf-engine=typst -V papersize=a4 -V fontsize=10pt -V margin-x=18mm -V margin-y=18mm --toc
```
Result: `article.pdf`, 35 pages. Checked pages 1-3, 20, 21 and 33 visually: tables of contents, diagram (lines shortened after the first render wrapped), code blocks, numbered list and Devanagari in the Hindi script render; Devanagari uses a fallback font and its conjuncts look slightly rough. Clean-up (sam delete) intentionally not run: the user wants to keep the stack for real Hindi and English recording tests.
