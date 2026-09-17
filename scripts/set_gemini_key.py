"""Pure memory-only reader for GEMINI_API_KEY.

Secrets exist only in memory and in GitHub Secrets.
Never written to disk, never in arguments, never in logs, never echoed.
"""
import getpass
import os
import socket
import subprocess
import sys
import urllib3.util.connection

try:
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

import requests

REPO = "bjviufutu-dot/multipost"
BASE_API = "https://generativelanguage.googleapis.com/v1beta"


def main():
    print("\n" + "=" * 65)
    print(" GEMINI API KEY IN-MEMORY UPDATE")
    print("=" * 65)

    key = getpass.getpass("Enter your new Gemini API Key (hidden, no echo): ").strip()
    if not key:
        print("[FAIL] Key cannot be empty.")
        sys.exit(1)

    print("\nVerifying key in memory with a test call...")
    try:
        r = requests.get(
            f"{BASE_API}/models",
            headers={"x-goog-api-key": key, "Accept": "application/json"},
            params={"key": key},
            timeout=15
        )
        if r.status_code == 200:
            print("  - API Key verified: True")
        else:
            print(f"  - API Key verified: False (HTTP {r.status_code})")
            sys.exit(1)
    except Exception as e:
        print(f"  - Verification call failed: {e}")
        sys.exit(1)

    print("Deploying key directly to GitHub repository secrets via stdin...")
    proc = subprocess.run(
        ["gh", "secret", "set", "GEMINI_API_KEY", "--repo", REPO],
        input=key.encode("utf-8"),
        capture_output=True
    )
    # Overwrite in-memory variable
    key = " " * len(key)
    del key

    if proc.returncode == 0:
        print("  - GEMINI_API_KEY set in repo secrets: True")
    else:
        print("  - GEMINI_API_KEY set in repo secrets: False")
        sys.exit(1)

    print("\nListing current repository secrets (names only):")
    subprocess.run(["gh", "secret", "list", "--repo", REPO])
    print("\n[SUCCESS] Key securely updated in GitHub Secrets without touching disk.\n")


if __name__ == "__main__":
    main()
