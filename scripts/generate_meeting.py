import boto3

polly = boto3.client("polly", region_name="us-east-1")

# (voice, line). Joanna plays the customer, Matthew plays the DevOps engineer.
TURNS = [
    ("Matthew", "Hi, this is Matthew from the DevOps team."),
    ("Joanna", "Hi Matthew, this is Priya from Acme Retail."),
    ("Matthew", "Thanks for joining, Priya. Today I want to cover the migration plan for the Acme Retail staging environment and agree on next steps."),
    ("Joanna", "Sure. Our main concern is downtime. The checkout service cannot be down during business hours."),
    ("Matthew", "Understood. We will do the cutover on Saturday night, between eleven p.m. and two a.m. We decided on a blue green deployment so we can roll back quickly."),
    ("Joanna", "Good. Let's make that official. The cutover window is Saturday, November twenty first."),
    ("Matthew", "Agreed. For that, I need the production database credentials rotated before the cutover. Priya, can your team handle that?"),
    ("Joanna", "Yes. My colleague Daniel will rotate the credentials by Wednesday, November eighteenth."),
    ("Matthew", "Great. I will send the updated runbook and the rollback checklist to everyone by Monday, November sixteenth."),
    ("Joanna", "One more thing. We need to review the monitoring dashboards. Somebody should check whether the alerts cover the payment service."),
    ("Matthew", "Right, that is still open. We have not decided who takes it, so let's revisit it on the next call."),
    ("Joanna", "Also, our CFO asked about the cost of running both environments in parallel."),
    ("Matthew", "I will prepare a cost estimate and share it by Friday, November twentieth."),
    ("Joanna", "Perfect. Anything else?"),
    ("Matthew", "No, that is everything. Thanks, Priya. Talk soon."),
]

with open("acme-migration-call.mp3", "wb") as out:
    for voice, text in TURNS:
        resp = polly.synthesize_speech(
            Text=text, OutputFormat="mp3", VoiceId=voice, Engine="neural"
        )
        out.write(resp["AudioStream"].read())
