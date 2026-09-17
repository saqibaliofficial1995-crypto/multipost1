#!/usr/bin/env python3
"""Multipost Setup Wizard — Interactive 8-Step Setup and Verification.

Features:
- 8 numbered, resumable steps tracked in .setup_state.json
- Sensitive input handled securely via getpass (never echoed or printed)
- GitHub Secrets set via stdin pipes to `gh secret set` (never command-line args)
- MinGit integration with `gh auth setup-git`
- Scope validation for YouTube (enforces both youtube.upload and youtube scopes;
  deletes tokens/yt_token.json and re-prompts if missing)
- Private repository verification via `gh repo view --json isPrivate`
- Fail-fast check on Meta short-lived token expiration
- Supports --check flag to execute only Step 1 preflight checks
- Supports --reset flag to clear progress state
"""

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE_FILE = Path(".setup_state.json")
TOKENS_DIR = Path("tokens")
CLIENT_SECRET_FILE = TOKENS_DIR / "google_client_secret.json"
YT_TOKEN_FILE = TOKENS_DIR / "yt_token.json"
META_TOKEN_FILE = TOKENS_DIR / "fb_page_token.json"
CONFIG_FILE = Path("config.yaml")
CONFIG_EXAMPLE_FILE = Path("config.example.yaml")

REQUIRED_YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive",
]


class WizardState:
    def __init__(self, state_file=STATE_FILE):
        self.state_file = state_file
        self.data = {"completed_steps": [], "config": {}}
        self.load()

    def load(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"completed_steps": [], "config": {}}

    def save(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def is_completed(self, step_number):
        return step_number in self.data.get("completed_steps", [])

    def mark_completed(self, step_number):
        if step_number not in self.data["completed_steps"]:
            self.data["completed_steps"].append(step_number)
            self.data["completed_steps"].sort()
            self.save()

    def set_val(self, key, val):
        self.data["config"][key] = val
        self.save()

    def get_val(self, key, default=None):
        return self.data["config"].get(key, default)

    def reset(self):
        if self.state_file.exists():
            self.state_file.unlink()
        self.data = {"completed_steps": [], "config": {}}


def banner(title):
    width = 65
    print("\n" + "=" * width)
    print(f" {title}")
    print("=" * width)


def step_header(num, title, completed=False):
    status = " [DONE]" if completed else ""
    banner(f"Step {num}/8: {title}{status}")


def should_skip_step(state, step_num):
    if state.is_completed(step_num):
        print(f"--> Step {step_num} is already completed per .setup_state.json. Skipping.")
        return True
    return False


# =====================================================================
# STEP 1: Preflight Checks
# =====================================================================
def step_1_preflight(exit_on_fail=True):
    banner("STEP 1: Preflight & Environment Checks")
    results = []

    # 1. Python Version (>= 3.10)
    py_ver = sys.version_info
    py_ok = (py_ver.major == 3 and py_ver.minor >= 10)
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    results.append(("Python (>= 3.10)", py_ok, f"v{py_str}"))

    # 2. Git
    git_path = shutil.which("git")
    git_ver = "Not found"
    if git_path:
        try:
            out = subprocess.check_output([git_path, "--version"], text=True).strip()
            git_ver = out
        except Exception:
            git_ver = "Error checking version"
    results.append(("git", bool(git_path), git_ver))

    # 3. FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_ver = "Not found"
    if ffmpeg_path:
        try:
            out = subprocess.check_output([ffmpeg_path, "-version"], text=True).splitlines()[0]
            ffmpeg_ver = out.split(" Copyright")[0]
        except Exception:
            ffmpeg_ver = "Installed"
    results.append(("ffmpeg", bool(ffmpeg_path), ffmpeg_ver))

    # 4. GitHub CLI (gh)
    gh_path = shutil.which("gh")
    gh_ver = "Not found"
    if gh_path:
        try:
            out = subprocess.check_output([gh_path, "--version"], text=True).splitlines()[0]
            gh_ver = out
        except Exception:
            gh_ver = "Installed"
    results.append(("gh (GitHub CLI)", bool(gh_path), gh_ver))

    # 5. Required Python dependencies
    deps = [
        ("googleapiclient", "google-api-python-client"),
        ("google.auth", "google-auth"),
        ("google_auth_oauthlib", "google-auth-oauthlib"),
        ("requests", "requests"),
        ("yaml", "PyYAML"),
        ("apscheduler", "APScheduler"),
        ("boto3", "boto3"),
    ]
    for mod_name, pkg_name in deps:
        try:
            __import__(mod_name)
            results.append((f"Python dep: {pkg_name}", True, "Installed"))
        except ImportError:
            results.append((f"Python dep: {pkg_name}", False, "Missing (pip install -r requirements.txt)"))

    # 6. Workspace Directories
    for d in ["tokens", "inbox", "processed", "work", "state"]:
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        results.append((f"Directory '{d}/'", p.is_dir(), "Ready"))

    # 7. Gitignore protection
    gi_path = Path(".gitignore")
    gi_ok = False
    if gi_path.exists():
        gi_content = gi_path.read_text(encoding="utf-8")
        tokens_ignored = "tokens/" in gi_content or "tokens" in gi_content
        state_ignored = ".setup_state.json" in gi_content
        gi_ok = tokens_ignored and state_ignored
    results.append((".gitignore (protects tokens & state)", gi_ok, "tokens/ and .setup_state.json ignored"))

    # Display results
    print("\nPreflight Checklist:")
    print("-" * 65)
    all_passed = True
    for item, status, detail in results:
        badge = "[ PASS ]" if status else "[ FAIL ]"
        if not status:
            all_passed = False
        print(f"{badge:10} {item:32} : {detail}")
    print("-" * 65)

    if all_passed:
        print("[SUCCESS] All preflight checks passed!\n")
    else:
        print("[WARNING] Some preflight checks failed. Please review above.\n")
        if exit_on_fail:
            sys.exit(1)

    return all_passed


# =====================================================================
# STEP 2: Google Client Secrets File Check
# =====================================================================
def step_2_check_google_secrets(state):
    step_header(2, "Google Cloud OAuth Client Credentials", state.is_completed(2))
    if should_skip_step(state, 2):
        return

    print("Checking tokens/google_client_secret.json...")
    if not CLIENT_SECRET_FILE.exists():
        print(f"[FAIL] {CLIENT_SECRET_FILE} not found!")
        print("Please place your Desktop OAuth client JSON at tokens/google_client_secret.json")
        sys.exit(1)

    try:
        with open(CLIENT_SECRET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[FAIL] Unable to parse {CLIENT_SECRET_FILE} as JSON: {e}")
        sys.exit(1)

    installed = data.get("installed") or data.get("web")
    if not installed:
        print("[FAIL] JSON missing 'installed' block. Ensure the OAuth client was created as a 'Desktop app'.")
        sys.exit(1)

    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")

    print(f"  - File exists: True")
    print(f"  - Valid JSON: True")
    print(f"  - Desktop app block ('installed'): True")
    print(f"  - client_id present: {bool(client_id)}")
    print(f"  - client_secret present: {bool(client_secret)}")

    if not (client_id and client_secret):
        print("[FAIL] client_id or client_secret is missing or empty inside the file!")
        sys.exit(1)

    state.set_val("client_id", client_id)
    state.mark_completed(2)
    print("\n[SUCCESS] Google OAuth Client Credentials verified.\n")


# =====================================================================
# STEP 3: YouTube OAuth Login & Scope Verification
# =====================================================================
def step_3_youtube_auth(state):
    step_header(3, "YouTube OAuth Login & Scope Check", state.is_completed(3))
    if should_skip_step(state, 3):
        return

    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    needs_login = True
    if YT_TOKEN_FILE.exists():
        try:
            with open(YT_TOKEN_FILE, "r", encoding="utf-8") as f:
                tok_data = json.load(f)
            granted_scopes = set(tok_data.get("scopes", []))
            has_all_scopes = all(s in granted_scopes for s in REQUIRED_YT_SCOPES)

            if not has_all_scopes:
                print(f"[NOTICE] Existing token at {YT_TOKEN_FILE} is missing required scopes.")
                print(f"Required scopes: {REQUIRED_YT_SCOPES}")
                print(f"Granted scopes:  {list(granted_scopes)}")
                print("Deleting outdated token and initiating fresh consent flow...")
                YT_TOKEN_FILE.unlink(missing_ok=True)
                needs_login = True
            else:
                creds = Credentials.from_authorized_user_file(str(YT_TOKEN_FILE), REQUIRED_YT_SCOPES)
                if creds and creds.valid:
                    print("  - Existing token is valid and contains all required scopes.")
                    needs_login = False
                elif creds and creds.expired and creds.refresh_token:
                    from google.auth.transport.requests import Request
                    creds.refresh(Request())
                    with open(YT_TOKEN_FILE, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                    print("  - Existing token successfully refreshed.")
                    needs_login = False
        except Exception as e:
            print(f"[WARN] Failed validating existing token ({e}). Re-authenticating...")
            YT_TOKEN_FILE.unlink(missing_ok=True)
            needs_login = True

    if needs_login:
        print("\nStarting local OAuth authentication server...")
        print("IMPORTANT: Since YouTube scopes are sensitive, Google will show an 'Unverified app' screen.")
        print("--> Click 'Advanced' -> 'Go to multipost (unsafe)' to proceed.")
        print("--> Log in with the Google Account managing your YouTube channel.\n")

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), REQUIRED_YT_SCOPES)
            creds = flow.run_local_server(
                port=0,
                access_type="offline",
                prompt="consent",
                authorization_prompt_message="\n[OAUTH_URL]: {url}\n\nOpen the above URL in your browser to authorize access.\n",
            )
        except Exception as e:
            err_str = str(e)
            if "invalid_client" in err_str:
                print("\n[FAILURE DIAGNOSIS]: 'invalid_client' detected!")
                print("--> The secret in tokens/google_client_secret.json does not match the active secret in Google Cloud.")
            elif "access_denied" in err_str:
                print("\n[FAILURE DIAGNOSIS]: 'access_denied' detected!")
                print("--> The login was declined, permissions were refused, or the wrong Google account was selected.")
            else:
                print(f"\n[FAILURE DIAGNOSIS]: OAuth login failed: {e}")
            sys.exit(1)

        if not creds.refresh_token:
            print("\n[FAILURE DIAGNOSIS]: Token returned WITHOUT a refresh_token!")
            print("--> Reason: The OAuth consent screen is not published to 'In production', or permissions must be revoked at https://myaccount.google.com/connections before re-prompting consent.")
            sys.exit(1)

        granted_scopes = set(creds.scopes or [])
        missing_scopes = [s for s in REQUIRED_YT_SCOPES if s not in granted_scopes]
        if missing_scopes:
            print(f"\n[FAILURE DIAGNOSIS]: Granted scopes missing required scopes: {missing_scopes}")
            print("--> Make sure to approve all requested scopes (YouTube and Google Drive).")
            sys.exit(1)

        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        with open(YT_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        try:
            os.chmod(YT_TOKEN_FILE, 0o600)
        except Exception:
            pass

    # Verify final token
    with open(YT_TOKEN_FILE, "r", encoding="utf-8") as f:
        final_tok = json.load(f)
    print(f"  - YouTube & Drive token saved: True")
    print(f"  - Refresh token present: {bool(final_tok.get('refresh_token'))}")
    granted_scopes = final_tok.get('scopes', [])
    print(f"  - Scope youtube.upload present: {'https://www.googleapis.com/auth/youtube.upload' in granted_scopes}")
    print(f"  - Scope youtube present: {'https://www.googleapis.com/auth/youtube' in granted_scopes}")
    print(f"  - Scope drive present: {'https://www.googleapis.com/auth/drive' in granted_scopes}")

    import requests
    ch_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {final_tok.get('token')}"},
        timeout=30
    )
    if ch_resp.status_code == 200:
        items = ch_resp.json().get("items", [])
        if items:
            ch_id = items[0].get("id")
            ch_title = items[0].get("snippet", {}).get("title")
            print(f"  - Channel Title: {ch_title}")
            print(f"  - Channel ID: {ch_id}")
            if ch_id == "UC6WQ7nljzB1DmVHP61LF3Ug":
                print("  - Channel confirmation: MATCH (UC6WQ7nljzB1DmVHP61LF3Ug)")
            else:
                print(f"  - Channel confirmation: MISMATCH (expected UC6WQ7nljzB1DmVHP61LF3Ug, got {ch_id})")

    state.mark_completed(3)
    print("\n[SUCCESS] YouTube & Drive OAuth completed and verified.\n")


# =====================================================================
# STEP 4: Meta Graph API Setup (Facebook & Instagram)
# =====================================================================
def step_4_meta_setup(state):
    step_header(4, "Meta Graph API (Facebook Page & Instagram)", state.is_completed(4))
    if should_skip_step(state, 4):
        return

    import requests

    GRAPH = "https://graph.facebook.com/v21.0"

    print("Configure Facebook Page and linked Instagram Business/Creator account.")
    print("Prerequisites: developers.facebook.com app with 'Facebook Login' and 'Instagram Graph API'.")
    print("Permissions required in Graph API Explorer:")
    print("  pages_show_list, pages_read_engagement, pages_manage_posts,")
    print("  instagram_basic, instagram_content_publish, business_management\n")

    app_id = input("Enter Meta App ID: ").strip()
    if not app_id:
        print("[FAIL] App ID cannot be empty.")
        sys.exit(1)
    state.set_val("meta_app_id", app_id)

    app_secret = getpass.getpass("Enter Meta App Secret (hidden): ").strip()
    if not app_secret:
        print("[FAIL] App Secret cannot be empty.")
        sys.exit(1)

    short_token = getpass.getpass("Enter Short-lived User Token from Graph API Explorer (hidden): ").strip()
    if not short_token:
        print("[FAIL] Short-lived token cannot be empty.")
        sys.exit(1)

    # 1. Exchange short-lived -> long-lived user token (with FAIL-FAST check)
    print("\n[1/2] Exchanging short-lived token for long-lived user token (60 days)...")
    try:
        resp = requests.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
            timeout=30,
        )
        data = resp.json()
        if "error" in data:
            err = data["error"]
            err_msg = err.get("message", "Unknown error")
            err_code = err.get("code", 0)
            print(f"\n[FAIL-FAST ERROR] Meta token exchange failed (Code {err_code}): {err_msg}")
            if err_code == 190 or "expired" in err_msg.lower():
                print("--> The short-lived user token has already expired! Generate a fresh token in Graph API Explorer and re-run.")
            sys.exit(1)
        resp.raise_for_status()
        long_user_token = data["access_token"]
        print("  - Long-lived user token obtained: True")
    except requests.RequestException as e:
        print(f"[FAIL-FAST ERROR] Network/HTTP error during Meta token exchange: {e}")
        sys.exit(1)

    # 2. Fetch Pages and never-expiring Page Tokens
    print("[2/2] Fetching Facebook Pages and linked Instagram accounts...")
    try:
        p_resp = requests.get(
            f"{GRAPH}/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id,username}",
                "access_token": long_user_token,
            },
            timeout=30,
        )
        p_resp.raise_for_status()
        pages = p_resp.json().get("data", [])
        if not pages:
            print("[FAIL] No Facebook Pages found for this account! Check your permissions.")
            sys.exit(1)
    except Exception as e:
        print(f"[FAIL] Error retrieving Facebook Pages: {e}")
        sys.exit(1)

    print(f"\nFound {len(pages)} Facebook Page(s):")
    for i, pg in enumerate(pages):
        ig = pg.get("instagram_business_account") or {}
        ig_status = f"IG User ID: {ig.get('id')} (@{ig.get('username')})" if ig.get("id") else "No linked IG"
        print(f"  [{i+1}] {pg['name']} (Page ID: {pg['id']}) | {ig_status}")

    # 3. Page selection logic (auto-select if exactly one with linked IG)
    pages_with_ig = [
        (i, pg)
        for i, pg in enumerate(pages)
        if pg.get("instagram_business_account") and pg["instagram_business_account"].get("id")
    ]

    selected_idx = 0
    if len(pages_with_ig) == 1:
        selected_idx = pages_with_ig[0][0]
        selected_page = pages[selected_idx]
        ig_acc = selected_page.get("instagram_business_account") or {}
        print(
            f"\n[AUTO-SELECT] Exactly one Page with a linked Instagram account found: "
            f"'{selected_page['name']}' (Page ID: {selected_page['id']}, IG: @{ig_acc.get('username')}). Automatically selected."
        )
    elif len(pages) > 1:
        choice = input(f"\nSelect Page number [1-{len(pages)}]: ").strip()
        try:
            selected_idx = int(choice) - 1
            if selected_idx < 0 or selected_idx >= len(pages):
                selected_idx = 0
        except ValueError:
            selected_idx = 0
        selected_page = pages[selected_idx]
        ig_acc = selected_page.get("instagram_business_account") or {}
    else:
        selected_page = pages[0]
        ig_acc = selected_page.get("instagram_business_account") or {}

    # 4. Check if chosen Page has no linked Instagram business account
    if not ig_acc.get("id"):
        print(f"\n[STOP] The chosen Page '{selected_page['name']}' (ID: {selected_page['id']}) has no linked Instagram business account!")
        print("--> Instagram publishing is impossible until you link an Instagram Professional/Creator account in the Instagram app or Facebook Page settings.")
        print("--> Please link your Instagram account to this Facebook Page and re-run.")
        sys.exit(1)

    # 5. Store the permanent Page token, FB page id, and IG user id
    payload = {
        "page_access_token": selected_page["access_token"],
        "page_id": selected_page["id"],
        "page_name": selected_page["name"],
        "ig_user_id": ig_acc.get("id"),
        "ig_username": ig_acc.get("username"),
        "note": "Never-expiring Page Access Token for Multipost.",
    }

    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    with open(META_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    try:
        os.chmod(META_TOKEN_FILE, 0o600)
    except Exception:
        pass

    state.set_val("page_id", selected_page["id"])
    state.set_val("page_name", selected_page["name"])
    state.set_val("ig_user_id", ig_acc.get("id"))
    state.set_val("ig_username", ig_acc.get("username"))

    # 6. Verify the Page token really works
    print("\n[VERIFICATION] Verifying Page token with Graph API calls...")
    try:
        v_pg = requests.get(
            f"{GRAPH}/{selected_page['id']}",
            params={"fields": "name", "access_token": selected_page["access_token"]},
            timeout=30,
        )
        v_pg.raise_for_status()
        v_pg_data = v_pg.json()
        print(f"  - GET /{selected_page['id']}?fields=name -> name: '{v_pg_data.get('name')}' (Valid: True)")

        v_ig = requests.get(
            f"{GRAPH}/{ig_acc['id']}",
            params={"fields": "username", "access_token": selected_page["access_token"]},
            timeout=30,
        )
        v_ig.raise_for_status()
        v_ig_data = v_ig.json()
        print(f"  - GET /{ig_acc['id']}?fields=username -> username: '@{v_ig_data.get('username')}' (Valid: True)")
    except Exception as e:
        print(f"[FAIL] Page token verification request failed: {e}")
        sys.exit(1)

    state.mark_completed(4)

    print(f"\n[SUCCESS] Meta Page Token verified and saved to {META_TOKEN_FILE}.")
    print(f"  - Page Name: {selected_page['name']}")
    print(f"  - Page ID: {selected_page['id']}")
    print(f"  - IG Username: @{ig_acc.get('username')}")
    print(f"  - IG User ID: {ig_acc.get('id')}")
    print(f"  - Permanent Token saved: True\n")


# =====================================================================
# STEP 5: Cloudflare R2 / S3 Storage Configuration
# =====================================================================
def step_5_s3_storage(state):
    step_header(5, "Cloudflare R2 / S3 Storage Configuration", state.is_completed(5))
    if should_skip_step(state, 5):
        return

    print("Cloudflare R2 / S3 is used for hosting videos with public URLs (required for Instagram & GitHub Actions).")
    ans = input("Do you want to configure Cloudflare R2 / S3 storage now? [Y/n]: ").strip().lower()
    if ans not in ("", "y", "yes"):
        print("--> Skipping Storage configuration for now.")
        state.mark_completed(5)
        return

    endpoint = input("S3_ENDPOINT (e.g., https://<account_id>.r2.cloudflarestorage.com): ").strip()
    bucket = input("S3_BUCKET name: ").strip()
    access_key = getpass.getpass("S3_ACCESS_KEY (hidden): ").strip()
    secret_key = getpass.getpass("S3_SECRET_KEY (hidden): ").strip()
    public_base = input("S3_PUBLIC_BASE URL (e.g., https://pub-xxx.r2.dev or custom domain): ").strip().rstrip("/")

    # Test S3 connectivity
    print("\nTesting S3 connectivity...")
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )
        s3.head_bucket(Bucket=bucket)
        print(f"  - Bucket '{bucket}' verified accessible: True")
    except Exception as e:
        print(f"[WARN] Bucket verification check raised an error: {e}")
        cont = input("Continue anyway? [y/N]: ").strip().lower()
        if cont not in ("y", "yes"):
            sys.exit(1)

    state.set_val("s3_endpoint", endpoint)
    state.set_val("s3_bucket", bucket)
    state.set_val("s3_public_base", public_base)
    # Store credentials temporarily in state only if needed for Step 8
    state.set_val("s3_configured", True)
    state.set_val("_tmp_s3_ak", access_key)
    state.set_val("_tmp_s3_sk", secret_key)

    state.mark_completed(5)
    print("\n[SUCCESS] Storage configuration verified.\n")


# =====================================================================
# STEP 6: Local Configuration File Setup (config.yaml)
# =====================================================================
def step_6_local_config(state):
    step_header(6, "Local Configuration Setup (config.yaml)", state.is_completed(6))
    if should_skip_step(state, 6):
        return

    import yaml

    if not CONFIG_FILE.exists():
        if CONFIG_EXAMPLE_FILE.exists():
            shutil.copyfile(CONFIG_EXAMPLE_FILE, CONFIG_FILE)
            print(f"Copied {CONFIG_EXAMPLE_FILE} -> {CONFIG_FILE}")
        else:
            print(f"[FAIL] {CONFIG_EXAMPLE_FILE} missing.")
            sys.exit(1)

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[FAIL] Error parsing {CONFIG_FILE}: {e}")
        sys.exit(1)

    # Populate IDs from Step 4
    page_id = state.get_val("page_id")
    ig_user_id = state.get_val("ig_user_id")

    if page_id:
        cfg.setdefault("facebook", {})["page_id"] = str(page_id)
    if ig_user_id:
        cfg.setdefault("instagram", {})["ig_user_id"] = str(ig_user_id)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    state.mark_completed(6)
    print(f"\n[SUCCESS] Local {CONFIG_FILE} configured with Facebook Page ID and Instagram User ID.\n")


# =====================================================================
# STEP 7: GitHub CLI Auth & Private Repository Verification
# =====================================================================
def step_7_github_repo_check(state):
    step_header(7, "GitHub CLI Auth & Private Repo Verification", state.is_completed(7))
    if should_skip_step(state, 7):
        return

    # 1. Check gh auth status
    print("Checking GitHub CLI authentication status...")
    gh_status = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if gh_status.returncode != 0:
        print("[FAIL] GitHub CLI is not logged in.")
        print("Please run: gh auth login")
        sys.exit(1)
    print("  - GitHub CLI authenticated: True")

    # 2. Run gh auth setup-git (crucial for MinGit)
    print("Configuring git credential helper via 'gh auth setup-git'...")
    setup_git = subprocess.run(["gh", "auth", "setup-git"], capture_output=True, text=True)
    if setup_git.returncode == 0:
        print("  - Git credentials configured for MinGit: True")
    else:
        print(f"  - Notice: {setup_git.stderr.strip() or setup_git.stdout.strip()}")

    # 3. Check if current directory is a git repo
    git_check = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    if git_check.returncode != 0:
        print("Initializing local git repository...")
        subprocess.run(["git", "init"], check=True)

    # 4. Verify GitHub remote repository is PRIVATE
    print("Verifying GitHub remote repository visibility...")
    repo_view = subprocess.run(
        ["gh", "repo", "view", "--json", "isPrivate,nameWithOwner,url"],
        capture_output=True,
        text=True,
    )

    if repo_view.returncode != 0:
        print("[NOTICE] No GitHub remote repository found for this directory.")
        create_ans = input("Would you like to create a new PRIVATE GitHub repository now? [Y/n]: ").strip().lower()
        if create_ans in ("", "y", "yes"):
            repo_name = input("Enter repository name [multipost]: ").strip() or "multipost"
            print(f"Creating private repository '{repo_name}' on GitHub...")
            cmd = ["gh", "repo", "create", repo_name, "--private", "--source=.", "--push"]
            create_res = subprocess.run(cmd, capture_output=True, text=True)
            if create_res.returncode != 0:
                print(f"[FAIL] Could not create repository: {create_res.stderr}")
                sys.exit(1)
            print("  - Private repository created and pushed: True")
            repo_view = subprocess.run(["gh", "repo", "view", "--json", "isPrivate,nameWithOwner"], capture_output=True, text=True)
        else:
            print("[WARN] Proceeding without remote repository check.")
            state.mark_completed(7)
            return

    try:
        repo_data = json.loads(repo_view.stdout)
        is_private = repo_data.get("isPrivate", False)
        repo_name = repo_data.get("nameWithOwner", "unknown")

        print(f"  - Repository: {repo_name}")
        print(f"  - isPrivate: {is_private}")

        if not is_private:
            banner("CRITICAL SECURITY ERROR: REPOSITORY IS PUBLIC")
            print(f"Repository '{repo_name}' is currently PUBLIC!")
            print("Multipost requires a PRIVATE repository so that workflow logs, tokens, and")
            print("configurations are never exposed to the public internet.")
            print("Change repository visibility to Private on GitHub before continuing:")
            print("  gh repo edit --visibility private")
            sys.exit(1)

        state.set_val("repo_name", repo_name)
        state.mark_completed(7)
        print("\n[SUCCESS] Private repository verified.\n")
    except Exception as e:
        print(f"[WARN] Unable to parse repository information: {e}")


# =====================================================================
# STEP 8: Push GitHub Secrets via Stdin
# =====================================================================
def step_8_github_secrets(state):
    step_header(8, "Configure GitHub Secrets (via Secure Stdin Pipes)", state.is_completed(8))
    if should_skip_step(state, 8):
        return

    print("Deploying encrypted secrets to GitHub Actions repository...")
    secrets_to_set = {}

    # 1. YouTube Secrets
    if CLIENT_SECRET_FILE.exists() and YT_TOKEN_FILE.exists():
        with open(CLIENT_SECRET_FILE, "r", encoding="utf-8") as f:
            c_data = json.load(f)
        with open(YT_TOKEN_FILE, "r", encoding="utf-8") as f:
            t_data = json.load(f)

        blob = c_data.get("installed") or c_data.get("web") or {}
        yt_client_id = t_data.get("client_id") or blob.get("client_id")
        yt_client_secret = t_data.get("client_secret") or blob.get("client_secret")
        yt_refresh_token = t_data.get("refresh_token")

        if yt_client_id and yt_client_secret and yt_refresh_token:
            secrets_to_set["YT_CLIENT_ID"] = yt_client_id
            secrets_to_set["YT_CLIENT_SECRET"] = yt_client_secret
            secrets_to_set["YT_REFRESH_TOKEN"] = yt_refresh_token

    # 2. Meta Secrets
    if META_TOKEN_FILE.exists():
        with open(META_TOKEN_FILE, "r", encoding="utf-8") as f:
            m_data = json.load(f)
        if m_data.get("page_access_token"):
            secrets_to_set["META_PAGE_TOKEN"] = m_data["page_access_token"]
        if m_data.get("page_id"):
            secrets_to_set["FB_PAGE_ID"] = str(m_data["page_id"])
        if m_data.get("ig_user_id"):
            secrets_to_set["IG_USER_ID"] = str(m_data["ig_user_id"])

    # 3. Storage Secrets (if configured)
    if state.get_val("s3_configured"):
        s3_ep = state.get_val("s3_endpoint")
        s3_bk = state.get_val("s3_bucket")
        s3_pb = state.get_val("s3_public_base")
        s3_ak = state.get_val("_tmp_s3_ak")
        s3_sk = state.get_val("_tmp_s3_sk")
        if s3_ep:
            secrets_to_set["S3_ENDPOINT"] = s3_ep
        if s3_bk:
            secrets_to_set["S3_BUCKET"] = s3_bk
        if s3_pb:
            secrets_to_set["S3_PUBLIC_BASE"] = s3_pb
        if s3_ak:
            secrets_to_set["S3_ACCESS_KEY"] = s3_ak
        if s3_sk:
            secrets_to_set["S3_SECRET_KEY"] = s3_sk

    if not secrets_to_set:
        print("[WARN] No secrets ready to upload.")
        return

    print(f"Setting {len(secrets_to_set)} secrets via stdin pipe to 'gh secret set'...")
    for sec_name, sec_val in secrets_to_set.items():
        # Pipe secret value via stdin to prevent exposing it in process arguments or logs
        proc = subprocess.run(
            ["gh", "secret", "set", sec_name],
            input=str(sec_val).encode("utf-8"),
            capture_output=True,
        )
        if proc.returncode == 0:
            print(f"  [SET] {sec_name}: True")
        else:
            print(f"  [ERROR] {sec_name}: Failed ({proc.stderr.decode('utf-8', errors='ignore').strip()})")

    # Clean up temporary secret values from state file
    state.data["config"].pop("_tmp_s3_ak", None)
    state.data["config"].pop("_tmp_s3_sk", None)
    state.save()

    state.mark_completed(8)
    banner("MULTIPOST SETUP COMPLETE!")
    print("All 8 steps completed successfully.")
    print("You can test your cloud workflow on GitHub Actions:")
    print("  Actions tab -> 'Daily Multipost Upload' -> 'Run workflow' (with dry_run=true)")


# =====================================================================
# Main Wizard Controller
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="Multipost Interactive Setup Wizard")
    parser.add_argument("--check", action="store_true", help="Run only Step 1 preflight checks and exit")
    parser.add_argument("--reset", action="store_true", help="Reset wizard progress state (.setup_state.json)")
    parser.add_argument("--stop-after-step", type=int, default=8, help="Stop wizard execution after specified step number (1-8)")
    args = parser.parse_args()

    state = WizardState()

    if args.reset:
        state.reset()
        print("Setup wizard progress state reset successfully.")
        return

    if args.check:
        ok = step_1_preflight(exit_on_fail=False)
        sys.exit(0 if ok else 1)

    banner("MULTIPOST INTERACTIVE SETUP WIZARD")
    print("This wizard will configure YouTube, Facebook, Instagram, Storage, and GitHub Secrets.")
    print("Progress is saved in .setup_state.json and can be resumed at any time.\n")

    steps = [
        (1, lambda: None if should_skip_step(state, 1) else step_1_preflight(exit_on_fail=True)),
        (2, lambda: step_2_check_google_secrets(state)),
        (3, lambda: step_3_youtube_auth(state)),
        (4, lambda: step_4_meta_setup(state)),
        (5, lambda: step_5_s3_storage(state)),
        (6, lambda: step_6_local_config(state)),
        (7, lambda: step_7_github_repo_check(state)),
        (8, lambda: step_8_github_secrets(state)),
    ]

    for num, func in steps:
        func()
        if num >= args.stop_after_step:
            print(f"\n[INFO] Stopped after Step {num} as requested. State saved in .setup_state.json.")
            break


if __name__ == "__main__":
    main()

