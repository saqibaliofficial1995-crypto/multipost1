"""Instagram Reels publishing client for CI using Graph API v21.0.

Flow:
1. Check 24-hour publishing limit (max 25 Reels).
2. Create Reels container via POST /{ig_user_id}/media.
3. Poll container status until FINISHED (up to 90 polls with 5s delay).
4. Publish container via POST /{ig_user_id}/media_publish.
5. Fetch and log Reel permalink.
"""
import os
import time
import requests

GRAPH = "https://graph.facebook.com/v21.0"


def is_available(cfg=None):
    """Checks whether Meta credentials are configured."""
    token = os.environ.get("META_PAGE_TOKEN")
    user_id = os.environ.get("IG_USER_ID") or (cfg.get("instagram", {}).get("ig_user_id") if cfg else None)
    return bool(token and user_id)


def _handle_graph_error(response, context="Graph API request"):
    """Parses Graph API error responses and raises human-readable messages for known error codes."""
    try:
        data = response.json()
        err = data.get("error", {})
        code = err.get("code")
        message = err.get("message", "Unknown error")
        subcode = err.get("error_subcode")

        if code == 190:
            raise RuntimeError(
                f"[ig] Meta Access Token has expired or is invalid (Error 190, subcode {subcode}): {message}. "
                "Please run setup_wizard.py Step 4 to generate a new long-lived token."
            )
        elif code == 200:
            raise RuntimeError(
                f"[ig] Meta permission error (Error 200): {message}. "
                "The token is missing required permissions (e.g. instagram_content_publish, pages_read_engagement). "
                "Verify your Meta app permissions and re-run setup_wizard.py."
            )
        else:
            raise RuntimeError(f"[ig] {context} failed (Error {code}): {message}")
    except (ValueError, KeyError):
        response.raise_for_status()


def check_publishing_limit(ig_user_id, token):
    """Checks the 24-hour content publishing limit.
    
    Returns:
        tuple: (allowed: bool, quota_usage: int, quota_total: int)
    """
    url = f"{GRAPH}/{ig_user_id}/content_publishing_limit"
    r = requests.get(
        url,
        params={"fields": "config,quota_usage", "access_token": token},
        timeout=30,
    )
    if r.status_code != 200:
        _handle_graph_error(r, "Checking publishing limit")

    data = r.json().get("data", [{}])[0]
    quota_usage = data.get("quota_usage", 0)
    config = data.get("config", {})
    quota_total = config.get("quota_total", 25)

    print(f"[ig] Publishing quota: {quota_usage}/{quota_total} used in last 24 hours.")
    if quota_usage >= 25 or quota_usage >= quota_total:
        return False, quota_usage, quota_total
    return True, quota_usage, quota_total


def upload(cfg, public_video_url, caption):
    """Publishes a Reel to Instagram via Graph API v21.0.
    
    Args:
        cfg (dict): Configuration dictionary.
        public_video_url (str): Directly downloadable URL for the video asset.
        caption (str): Caption text (truncated to 2200 characters).
        
    Returns:
        tuple: (media_id, permalink)
    """
    if not is_available(cfg):
        print("[ig] SKIPPED: META_PAGE_TOKEN and/or IG_USER_ID are unset.")
        return None, ""

    token = os.environ.get("META_PAGE_TOKEN")
    user_id = os.environ.get("IG_USER_ID") or cfg.get("instagram", {}).get("ig_user_id")

    # 1. Check 24-hour publishing limit
    try:
        allowed, quota_usage, quota_total = check_publishing_limit(user_id, token)
        if not allowed:
            print(f"[ig] Skipped: 24-hour publishing limit reached ({quota_usage}/{quota_total}).")
            return None, ""
    except Exception as e:
        print(f"[ig] Notice: Could not verify publishing limit: {e}")

    # 2. Create Reels container
    print(f"[ig] Creating Reel container for user {user_id}...")
    container_payload = {
        "media_type": "REELS",
        "video_url": public_video_url,
        "caption": (caption or "")[:2200],
        "share_to_feed": "true",
        "access_token": token,
    }
    r = requests.post(f"{GRAPH}/{user_id}/media", data=container_payload, timeout=120)
    if r.status_code != 200:
        _handle_graph_error(r, "Creating Reel container")

    container_id = r.json().get("id")
    print(f"[ig] Reel container created: {container_id}")

    # 3. Poll status until FINISHED (up to 90 polls with 5s delay = 7.5 mins)
    for attempt in range(1, 91):
        time.sleep(5)
        poll_resp = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=60,
        )
        if poll_resp.status_code != 200:
            _handle_graph_error(poll_resp, f"Polling container status (poll {attempt})")

        poll_data = poll_resp.json()
        code = poll_data.get("status_code")
        status_desc = poll_data.get("status", "")
        print(f"[ig] Poll {attempt}/90: status_code={code} ({status_desc})", flush=True)

        if code == "FINISHED":
            break
        elif code == "ERROR":
            raise RuntimeError(f"[ig] Reel video processing failed in container: {status_desc}")
    else:
        raise TimeoutError(f"[ig] Reel container {container_id} did not reach FINISHED status within 450 seconds.")

    # 4. Publish media container
    print(f"[ig] Publishing container {container_id}...")
    pub_resp = requests.post(
        f"{GRAPH}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=120,
    )
    if pub_resp.status_code != 200:
        _handle_graph_error(pub_resp, "Publishing Reel container")

    media_id = pub_resp.json().get("id")
    print(f"[ig] Reel published successfully with media ID: {media_id}")

    # 5. Fetch and log permalink
    permalink = ""
    try:
        pl_resp = requests.get(
            f"{GRAPH}/{media_id}",
            params={"fields": "permalink", "access_token": token},
            timeout=60,
        )
        if pl_resp.status_code == 200:
            permalink = pl_resp.json().get("permalink", "")
            print(f"[ig] Reel permalink: {permalink}")
    except Exception as e:
        print(f"[ig] Notice: Could not fetch permalink: {e}")

    return media_id, permalink
