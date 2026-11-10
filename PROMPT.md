Continue the project in this folder: a serverless "meeting to MOM" pipeline on AWS. Starter files already exist (template.yaml, statemachine/mom.asl.json, src/*/app.py, scripts/generate_meeting.py, tests/, README.md). They were written without being run against AWS. Review them critically, fix what is wrong, and do not rewrite what already works.

GOAL
Upload an audio recording to S3. A Step Functions workflow transcribes it with Amazon Transcribe, extracts minutes of meeting (summary, decisions, action items with owner and due date) with Amazon Bedrock as validated JSON, and emails the result through SNS.

SPEC (the starter files already follow this; check them against it)
- Region us-east-1, Python 3.12 Lambdas, AWS SAM, one `sam deploy`.
- One S3 bucket. Recordings go in `uploads/`, transcripts in `transcripts/`. An EventBridge rule on S3 "Object Created" events for the `uploads/` prefix only starts the state machine, so it cannot loop.
- Three Lambdas: start_job, check_job, extract_mom (reads the transcript JSON, calls Bedrock Converse with temperature 0, validates the JSON, retries once with the error message, builds the email text).
- State machine: StartTranscription, Wait 20s, CheckTranscription, Choice (COMPLETED goes on, FAILED fails, otherwise loop back to Wait), ExtractMom with Retry and Catch, SendMom (SNS publish). If extraction fails, publish a failure email and end in a Fail state.
- MOM JSON shape: summary (string), decisions (list of strings), action_items (list of {task, owner or null, due_date or null}). Never guess an owner or date: use null. Copy dates as spoken.
- Least-privilege IAM. SNS email subscription takes the address from a template parameter.
- Test audio: scripts/generate_meeting.py uses Amazon Polly to read a fake 2-minute customer call. One action item has NO owner on purpose, to test that the pipeline reports "no owner" instead of inventing one.
- Local unit tests for validation, retry and email formatting (no AWS calls).

RULES
1. Before any command that creates, changes or deletes AWS resources, show me the command and wait for my approval. Before deploying, remind me to set an AWS Budgets alert.
2. Never print or store my AWS credentials. Use my existing CLI profile.
3. Do not assume APIs, model IDs or syntax. Check the current AWS docs. If Bedrock model access is not enabled, tell me what to enable in the console instead of working around it.
4. Run the unit tests and lint the template (cfn-lint or `sam validate`) before deploying.
5. Keep a file TESTLOG.md. For every test run, record the real command, the real output, every error message in full, what you changed to fix it, timestamps, and the cost shown in AWS billing or the Transcribe and Bedrock usage details. Never invent or estimate a number you can look up. If a number is not available yet (billing lags), write "not available yet".
6. Compare the real email with the answer key in README.md and report each item as correct or wrong. Say honestly if the model invented anything.
7. When everything passes, run `sam delete` after emptying the bucket (ask me first), then confirm nothing is left behind.

DOCUMENT
Then write article.md for AWS Builder Center, first person, from a DevOps engineer who writes MOMs after customer meetings. It must teach implementation: why each choice was made, the full code and commands, deploy, verify, clean up, a "what went wrong and how I fixed it" section from TESTLOG.md only, a measured-cost section from real numbers only, and tradeoffs. Leave clearly marked TODO placeholders for screenshots I must take myself (S3 upload, Step Functions execution graph, the MOM email). Do not make any claim that is not backed by TESTLOG.md or the AWS docs. Then convert it to PDF if pandoc or another tool is available; otherwise tell me what to install.

Start by reviewing the starter files and showing me your plan and a list of problems you found. Wait for my approval before changing code or touching AWS.
