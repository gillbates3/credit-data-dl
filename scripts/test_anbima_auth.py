import os
import sys
import requests
import base64
import json
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(".env.local")
load_dotenv(env_path)

client_id = os.getenv("ANBIMA_CLIENT_ID") or os.getenv("CLIENT_ID")
client_secret = os.getenv("ANBIMA_CLIENT_SECRET") or os.getenv("CLIENT_SECRET")

token_url = "https://api.anbima.com.br/oauth/access-token"
auth_str = f"{client_id}:{client_secret}"
headers = {
    "Authorization": f"Basic {base64.b64encode(auth_str.encode()).decode()}",
    "Content-Type": "application/json"
}
resp = requests.post(token_url, headers=headers, json={"grant_type": "client_credentials"})
access_token = resp.json().get("access_token")

api_headers = {
    "client_id": client_id,
    "access_token": access_token,
    "Accept": "application/json"
}

ticker = "ALAR14"
endpoints = {
    "caracteristicas": f"https://api-sandbox.anbima.com.br/feed/precos-indices/v1/debentures/{ticker}/caracteristicas",
    "secundario": "https://api-sandbox.anbima.com.br/feed/precos-indices/v1/debentures/mercado-secundario?data=2024-05-02",
    "ticker_base": f"https://api-sandbox.anbima.com.br/feed/precos-indices/v1/debentures/{ticker}"
}

results = {}
for name, url in endpoints.items():
    r = requests.get(url, headers=api_headers)
    results[name] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:200]}

with open("test_out.json", "w") as f:
    json.dump(results, f, indent=2)
