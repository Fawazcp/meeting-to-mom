"""Synthetic Hindi/English (Hinglish) 2-person call with Amazon Polly, for testing only.
Arjun (generative, male) plays the DevOps engineer, Kajal (neural, female) plays the customer.
Polly is a synthetic voice: it proves the pipeline handles Hindi text, not real-world audio quality."""
import boto3

polly = boto3.client("polly", region_name="us-east-1")

TURNS = [
    ("Arjun", "generative", "नमस्ते, मैं अर्जुन हूँ, DevOps टीम से।"),
    ("Kajal", "neural", "नमस्ते अर्जुन, मैं प्रिया हूँ, Acme Retail से।"),
    ("Arjun", "generative", "धन्यवाद प्रिया। आज हमें Acme Retail के staging environment के migration plan पर बात करनी है।"),
    ("Kajal", "neural", "ठीक है। हमारी मुख्य चिंता downtime की है। checkout service business hours में बंद नहीं होनी चाहिए।"),
    ("Arjun", "generative", "समझ गया। हम शनिवार रात ग्यारह बजे से सुबह दो बजे के बीच cutover करेंगे। हमने blue green deployment करने का फैसला किया है ताकि rollback जल्दी हो सके।"),
    ("Kajal", "neural", "बहुत अच्छा। तो cutover शनिवार, इक्कीस नवंबर को होगा।"),
    ("Arjun", "generative", "जी। इसके लिए production database के credentials cutover से पहले rotate होने चाहिए। प्रिया, क्या आपकी टीम यह कर सकती है?"),
    ("Kajal", "neural", "हाँ। मेरे सहकर्मी डेनियल बुधवार, अठारह नवंबर तक credentials rotate कर देंगे।"),
    ("Arjun", "generative", "बढ़िया। मैं अपडेटेड runbook और rollback checklist सोमवार, सोलह नवंबर तक सबको भेज दूँगा।"),
    ("Kajal", "neural", "एक और बात। हमें monitoring dashboards देखने होंगे। किसी को यह जाँचना चाहिए कि alerts payment service को cover करते हैं या नहीं।"),
    ("Arjun", "generative", "सही है, यह अभी खुला है। हमने तय नहीं किया कि यह कौन करेगा, इसलिए अगली call में इस पर दोबारा बात करेंगे।"),
    ("Kajal", "neural", "हमारे CFO ने दोनों environments एक साथ चलाने की लागत के बारे में भी पूछा था।"),
    ("Arjun", "generative", "मैं cost estimate तैयार करके शुक्रवार, बीस नवंबर तक साझा कर दूँगा।"),
    ("Kajal", "neural", "बहुत बढ़िया। और कुछ?"),
    ("Arjun", "generative", "नहीं, बस इतना ही। धन्यवाद प्रिया।"),
]

with open("acme-migration-call-hindi.mp3", "wb") as out:
    for voice, engine, text in TURNS:
        resp = polly.synthesize_speech(
            Text=text, OutputFormat="mp3", VoiceId=voice, Engine=engine, LanguageCode="hi-IN"
        )
        out.write(resp["AudioStream"].read())
