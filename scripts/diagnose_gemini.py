"""Diagnose Gemini API key permissions, project information, and model availability.

Runs with GEMINI_API_KEY from environment without leaking the key.
"""
import os
import sys
import json
import requests

BASE_API = "https://generativelanguage.googleapis.com/v1beta"
key = os.environ.get("GEMINI_API_KEY")

if not key:
    print("[ERROR] GEMINI_API_KEY is not set in environment.")
    sys.exit(1)

headers = {"x-goog-api-key": key, "Accept": "application/json"}
params = {"key": key}

print("=================================================================")
print(" GEMINI API DIAGNOSTIC REPORT")
print("=================================================================")

# -------------------------------------------------------------
# 1. Bare GET on models/gemini-flash-latest
# -------------------------------------------------------------
print("\n--- [1] BARE GET on models/gemini-flash-latest ---")
url_bare = f"{BASE_API}/models/gemini-flash-latest"
try:
    r_bare = requests.get(url_bare, headers=headers, params=params, timeout=20)
    print(f"HTTP Status: {r_bare.status_code}")
    print("Verbatim Response Body:")
    print(r_bare.text)
except Exception as e:
    print(f"Request failed: {e}")

# -------------------------------------------------------------
# 2. Check if project information is exposed
# -------------------------------------------------------------
print("\n--- [2] PROJECT INFORMATION DETECTION ---")
# Check response headers from API for project number or project id
project_header_keys = [k for k in r_bare.headers.keys() if "project" in k.lower() or "google" in k.lower()]
project_headers = {k: r_bare.headers[k] for k in project_header_keys if "key" not in k.lower()}
if project_headers:
    print(f"Relevant Response Headers: {project_headers}")
else:
    print("Project Information Exposed by API: None (Google Generative Language API does not expose the project ID/number in standard model responses).")

# -------------------------------------------------------------
# 3. Test generateContent on 3 models in specified order
# -------------------------------------------------------------
models_to_test = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
]

payload = {
    "contents": [{"parts": [{"text": "Reply with only the word OK"}]}],
    "generationConfig": {"temperature": 0.1}
}

print("\n--- [3] GENERATECONTENT TESTS ---")
for model in models_to_test:
    url_gen = f"{BASE_API}/models/{model}:generateContent"
    print(f"\n>> Testing model: {model}")
    try:
        r_gen = requests.post(url_gen, headers={"x-goog-api-key": key, "Content-Type": "application/json"}, params=params, json=payload, timeout=25)
        print(f"HTTP Status: {r_gen.status_code}")
        print("Verbatim Response Body:")
        print(r_gen.text)
    except Exception as e:
        print(f"Request error: {e}")

print("\n=================================================================\n")
