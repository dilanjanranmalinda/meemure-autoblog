import os, time, json, sys, re
from urllib.parse import urlparse, parse_qs
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/blogger"]
CODE_FILE = "/tmp/meemure_code.txt"

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials.json", SCOPES, redirect_uri="http://localhost:8080/"
)

auth_url, _ = flow.authorization_url(
    access_type="offline",
    prompt="consent",
    include_granted_scopes="true",
)
with open("/tmp/meemure_auth_url.txt", "w") as f:
    f.write(auth_url)

if os.path.exists(CODE_FILE):
    os.remove(CODE_FILE)

print("waiting for code...", flush=True)
while not os.path.exists(CODE_FILE):
    time.sleep(2)

raw = open(CODE_FILE).read().strip()
if raw.startswith("http"):
    parsed = urlparse(raw)
    code = parse_qs(parsed.query).get("code", [None])[0]
elif raw.startswith("code="):
    code = parse_qs(raw.split("?", 1)[-1]).get("code", [None])[0]
else:
    code = raw

if not code:
    print("no code found in input; dumping raw:", raw[:300], flush=True)
    sys.exit(1)

flow.fetch_token(code=code)

with open("token.json", "w") as f:
    f.write(flow.credentials.to_json())

print("Saved token.json successfully!", flush=True)