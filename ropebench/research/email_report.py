"""Send a progress email via Resend. Key from /root/.secrets/ropebench-resend.env (ROTATE)."""
import json
import sys
import urllib.request


def load_key():
    for line in open("/root/.secrets/ropebench-resend.env"):
        if line.startswith("RESEND_API_KEY="):
            return line.split("=",1)[1].strip()
    raise SystemExit("no resend key")

def send(subject: str, html: str, to="aidanpierce72@gmail.com"):
    key = load_key()
    body = json.dumps({
        "from": "RopeBench <onboarding@resend.dev>",
        "to": [to], "subject": subject, "html": html,
    }).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("sent:", r.status, r.read().decode()[:200])
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:300])

if __name__ == "__main__":
    send(sys.argv[1], sys.stdin.read())
