"""AI-powered YouTube & Reels metadata generator using Google Gemini.

Features:
1. Video Multimodal Analysis:
   - Uploads normalized MP4 to Gemini Files API (resumable protocol).
   - Waits for state to become ACTIVE.
   - Prompts Gemini to analyze visual scenes, luxury elements, and narrative.
   - Deletes uploaded file from Gemini Files API in a finally block.
2. Model Discovery:
   - Dynamically checks available models for the user's API key.
   - Chooses the best free-tier model supporting video (e.g. gemini-2.0-flash or gemini-1.5-flash).
3. Fallback Hierarchy:
   - Video analysis (video_ai_gemini)
   - Text-only Gemini call (text_ai_gemini)
   - Topic & config default metadata (topic_default_fallback)
   - Publishing never breaks if AI fails.
4. Output Schema & Strict YouTube Constraints:
   - title: under 60 characters, main keyword near front, no clickbait/ALL CAPS.
   - description: 3 to 5 lines. Hook in first 2 lines. Natural sentences.
   - tags: 10 to 15 items, total under 460 characters. Includes 'shorts' if duration <= 60s.
   - hashtags: exactly 3, appended to description.
"""
import json
import os
import re
import socket
import time
import urllib3.util.connection

try:
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

import requests

BASE_API = "https://generativelanguage.googleapis.com/v1beta"
UPLOAD_API = "https://generativelanguage.googleapis.com/upload/v1beta/files"


def clean_text(text):
    """Removes excessive emoji-spam and shouty ALL CAPS."""
    if not text:
        return ""
    # Strip excessive consecutive emojis (limit to max 1)
    text = re.sub(r"([\U00010000-\U0010ffff\u2600-\u27bf]){2,}", r"\1", text)
    # If text is predominantly ALL CAPS (and > 10 chars), convert to capitalized sentence
    letters = [c for c in text if c.isalpha()]
    if letters and (sum(1 for c in letters if c.isupper()) / len(letters)) > 0.6:
        text = text.capitalize()
    return text.strip()


def validate_metadata(data, duration=0, channel_topic=""):
    """Validates the AI output strictly against YouTube requirements."""
    if not isinstance(data, dict):
        return None

    title = clean_text(str(data.get("title", "")))
    raw_desc = str(data.get("description", "")).strip()
    tags = data.get("tags", [])
    hashtags = data.get("hashtags", [])

    # Title must be under 60 characters and non-empty
    if not title or len(title) >= 60:
        return None

    # Description lines check (3 to 5 lines)
    desc_lines = [clean_text(l) for l in raw_desc.splitlines() if l.strip()]
    if len(desc_lines) < 2:
        return None
    if len(desc_lines) > 5:
        desc_lines = desc_lines[:5]
    desc = "\n".join(desc_lines)

    # Validate tags (10 to 15 items, total under 460 chars)
    if not isinstance(tags, list):
        return None

    clean_tags = []
    seen = set()
    for t in tags:
        clean_t = re.sub(r"[#,\n\r]", "", str(t)).strip()
        if clean_t and clean_t.lower() not in seen:
            seen.add(clean_t.lower())
            clean_tags.append(clean_t)

    if len(clean_tags) < 5:
        return None
    clean_tags = clean_tags[:15]

    # For videos <= 60s, keep 'shorts' in tags
    if duration <= 60:
        if "shorts" not in [t.lower() for t in clean_tags]:
            clean_tags.insert(0, "shorts")
            if len(clean_tags) > 15:
                clean_tags = clean_tags[:15]

    # Enforce total tags string length under 460 characters
    while clean_tags and len(",".join(clean_tags)) >= 460:
        clean_tags.pop()

    if not clean_tags:
        return None

    # Exactly 3 clean hashtags
    clean_hashtags = []
    for h in hashtags:
        tag = re.sub(r"[^A-Za-z0-9_]", "", str(h)).strip()
        if tag and f"#{tag}" not in clean_hashtags:
            clean_hashtags.append(f"#{tag}")

    backup_pool = [re.sub(r"[^A-Za-z0-9_]", "", t) for t in clean_tags if t.lower() != "shorts"]
    if channel_topic:
        backup_pool.insert(0, re.sub(r"[^A-Za-z0-9_]", "", channel_topic))
    for candidate in backup_pool:
        if len(clean_hashtags) >= 3:
            break
        if candidate and f"#{candidate}" not in clean_hashtags:
            clean_hashtags.append(f"#{candidate}")

    clean_hashtags = clean_hashtags[:3]

    # Append the 3 hashtags to the end of the description
    if clean_hashtags:
        ht_line = " ".join(clean_hashtags)
        if ht_line not in desc:
            desc = f"{desc}\n\n{ht_line}"

    return {
        "title": title,
        "description": desc,
        "tags": clean_tags,
        "hashtags": clean_hashtags
    }


def discover_model(api_key):
    """Discovers available models for the given API key and selects the best free-tier video model."""
    preferred = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-002",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro",
    ]
    headers = {"x-goog-api-key": api_key, "Accept": "application/json"}
    try:
        r = requests.get(f"{BASE_API}/models", headers=headers, params={"key": api_key}, timeout=15)
        if r.status_code == 200:
            models_data = r.json().get("models", [])
            supported = [
                m.get("name", "").replace("models/", "")
                for m in models_data
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            print(f"[llm_meta] Supported models: {supported}")
            for pref in preferred:
                if pref in supported:
                    return pref
            for s in supported:
                if "2.0-flash" in s or "1.5-flash" in s:
                    return s
            if supported:
                return supported[0]
        else:
            print(f"[llm_meta] Models list failed (HTTP {r.status_code}): {r.text}")
    except Exception as e:
        print(f"[llm_meta] Model discovery warning: {e}")
    return "gemini-1.5-flash"


def upload_video_to_gemini(video_path, api_key):
    """Uploads a video to Gemini Files API using resumable upload and waits until ACTIVE."""
    file_size = os.path.getsize(video_path)
    display_name = os.path.basename(video_path)
    mime_type = "video/mp4"

    # 1. Initiate resumable upload
    init_headers = {
        "x-goog-api-key": api_key,
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json"
    }
    init_body = json.dumps({"file": {"display_name": display_name}})
    init_resp = requests.post(
        UPLOAD_API,
        headers=init_headers,
        params={"key": api_key},
        data=init_body,
        timeout=30
    )
    if init_resp.status_code != 200:
        print(f"[llm_meta] Files API init failed (HTTP {init_resp.status_code}): {init_resp.text}")
        init_resp.raise_for_status()

    upload_url = init_resp.headers.get("X-Goog-Upload-URL") or init_resp.headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("Missing X-Goog-Upload-URL in Gemini Files API response")

    # 2. Upload file content
    with open(video_path, "rb") as f:
        file_bytes = f.read()

    upload_headers = {
        "x-goog-api-key": api_key,
        "Content-Length": str(file_size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize"
    }
    upload_resp = requests.post(upload_url, headers=upload_headers, data=file_bytes, timeout=180)
    if upload_resp.status_code != 200:
        print(f"[llm_meta] Files API upload chunk failed (HTTP {upload_resp.status_code}): {upload_resp.text}")
        upload_resp.raise_for_status()

    file_info = upload_resp.json().get("file", {})
    remote_name = file_info.get("name")
    remote_uri = file_info.get("uri")

    # 3. Wait for processing to become ACTIVE
    start_time = time.time()
    while time.time() - start_time < 120:
        poll_resp = requests.get(
            f"{BASE_API}/{remote_name}",
            headers={"x-goog-api-key": api_key},
            params={"key": api_key},
            timeout=20
        )
        if poll_resp.status_code != 200:
            print(f"[llm_meta] Files API poll error (HTTP {poll_resp.status_code}): {poll_resp.text}")
        poll_resp.raise_for_status()
        state = poll_resp.json().get("state")
        if state == "ACTIVE":
            return remote_name, remote_uri
        elif state == "FAILED":
            raise RuntimeError(f"Gemini file state FAILED for {remote_name}")
        time.sleep(3)

    raise TimeoutError(f"Gemini file processing timed out for {remote_name}")


def delete_gemini_file(remote_name, api_key):
    """Deletes an uploaded file from Gemini Files API."""
    if not remote_name:
        return
    try:
        requests.delete(
            f"{BASE_API}/{remote_name}",
            headers={"x-goog-api-key": api_key},
            params={"key": api_key},
            timeout=15
        )
    except Exception:
        pass


def generate_from_video(video_path, duration, channel_topic, api_key, model_name):
    """Analyzes the video using Gemini multimodal input."""
    remote_name = None
    try:
        print(f"[llm_meta] Uploading video to Gemini Files API ({os.path.basename(video_path)})...")
        remote_name, remote_uri = upload_video_to_gemini(video_path, api_key)
        print(f"[llm_meta] Video uploaded and ACTIVE ({remote_name}). Analyzing content...")

        prompt = f"""You are an elite YouTube SEO metadata specialist.
Analyze this video carefully.
Channel topic / niche: '{channel_topic}'.
Video duration: {duration} seconds.

Inspect the visual scenes, subjects, aesthetic, luxury elements, actions, and narrative in the video.
Based on what ACTUALLY occurs in the video (ignore generic UUID filenames), generate optimized metadata for high click-through rate.

Output MUST be raw valid JSON adhering strictly to this schema:
{{
  "title": "Engaging, high-CTR title UNDER 60 characters with the primary keyword near the beginning based on the video scenes. No clickbait padding and no ALL CAPS.",
  "description": "3 to 5 lines total. The first 2 lines must carry a compelling hook visible before 'more'. Followed by natural sentences describing the video with high-ranking keywords.",
  "tags": ["10 to 15 tag keywords mixing broad and specific, total under 450 characters"],
  "hashtags": ["Three relevant hashtags without '#', exactly 3 items"]
}}
"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"fileData": {"mimeType": "video/mp4", "fileUri": remote_uri}},
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json"
            }
        }

        gen_url = f"{BASE_API}/models/{model_name}:generateContent"
        resp = requests.post(
            gen_url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            params={"key": api_key},
            json=payload,
            timeout=90
        )
        if resp.status_code != 200:
            print(f"[llm_meta] Video generateContent error (HTTP {resp.status_code}): {resp.text}")
            resp.raise_for_status()

        cand = resp.json().get("candidates", [{}])[0]
        text_content = cand.get("content", {}).get("parts", [{}])[0].get("text", "")

        parsed = json.loads(text_content)
        validated = validate_metadata(parsed, duration=duration, channel_topic=channel_topic)
        if validated:
            validated["path_used"] = "video_ai_gemini"
            return validated
    finally:
        if remote_name:
            print(f"[llm_meta] Cleaning up Gemini file {remote_name}...")
            delete_gemini_file(remote_name, api_key)

    return None


def generate_from_text(duration, channel_topic, api_key, model_name, filename=""):
    """Text-only Gemini fallback using channel topic and video duration."""
    prompt = f"""You are an elite YouTube SEO metadata specialist.
Generate optimized video metadata for a YouTube video.
Channel topic / niche: '{channel_topic}'.
Video duration: {duration} seconds.

Output MUST be raw valid JSON adhering strictly to this schema:
{{
  "title": "Engaging, high-CTR title UNDER 60 characters with the primary keyword near the beginning for this niche. No clickbait padding and no ALL CAPS.",
  "description": "3 to 5 lines total. The first 2 lines must carry a compelling hook visible before 'more'. Followed by natural sentences with high-ranking keywords.",
  "tags": ["10 to 15 tag keywords mixing broad and specific, total under 450 characters"],
  "hashtags": ["Three relevant hashtags without '#', exactly 3 items"]
}}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json"
        }
    }
    try:
        gen_url = f"{BASE_API}/models/{model_name}:generateContent"
        resp = requests.post(
            gen_url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            params={"key": api_key},
            json=payload,
            timeout=30
        )
        if resp.status_code != 200:
            print(f"[llm_meta] Text generateContent error (HTTP {resp.status_code}): {resp.text}")
            resp.raise_for_status()

        cand = resp.json().get("candidates", [{}])[0]
        text_content = cand.get("content", {}).get("parts", [{}])[0].get("text", "")

        parsed = json.loads(text_content)
        validated = validate_metadata(parsed, duration=duration, channel_topic=channel_topic)
        if validated:
            validated["path_used"] = "text_ai_gemini"
            return validated
    except Exception as e:
        print(f"[llm_meta] Text-only Gemini call error: {e}")

    return None


def fallback_metadata(duration=0, channel_topic="", default_desc="", default_tags=None):
    """Safe fallback based on channel topic and configuration defaults."""
    topic = channel_topic or "Luxury Lifestyle"
    title = f"{topic} Highlights"[:59]

    tags = list(default_tags) if default_tags else ["shorts", "viral", "luxury", "lifestyle"]
    if duration <= 60 and "shorts" not in [t.lower() for t in tags]:
        tags.insert(0, "shorts")
    tags = tags[:15]

    hashtags = ["#shorts", "#luxury", "#lifestyle"]
    desc = default_desc or f"Experience the finest {topic.lower()}.\nFollow for daily luxury updates.\nExclusive highlights."
    desc = f"{desc}\n\n{' '.join(hashtags)}"

    return {
        "title": title,
        "description": desc,
        "tags": tags,
        "hashtags": hashtags,
        "path_used": "topic_default_fallback"
    }


def generate_metadata(video_path=None, filename="", duration=0, channel_topic="", api_key=None, default_desc="", default_tags=None):
    """Main entry point: Generates metadata with multi-tier fallback.

    Tier 1: Multimodal video analysis via Gemini Files API (video_ai_gemini).
    Tier 2: Text-only Gemini call using channel topic and duration (text_ai_gemini).
    Tier 3: Channel topic and config defaults (topic_default_fallback).
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")

    if key:
        chosen_model = discover_model(key)
        print(f"[llm_meta] Using Gemini model: {chosen_model}")

        # Tier 1: Multimodal video analysis
        if video_path and os.path.exists(video_path):
            try:
                res = generate_from_video(video_path, duration, channel_topic, key, chosen_model)
                if res:
                    print(f"[llm_meta] Generated metadata via Tier 1 ({res['path_used']}).")
                    return res
            except Exception as e:
                print(f"[llm_meta] Tier 1 video analysis failed ({e}). Falling back to Tier 2.")

        # Tier 2: Text-only Gemini call
        try:
            res = generate_from_text(duration, channel_topic, key, chosen_model, filename)
            if res:
                print(f"[llm_meta] Generated metadata via Tier 2 ({res['path_used']}).")
                return res
        except Exception as e:
            print(f"[llm_meta] Tier 2 text generation failed ({e}). Falling back to Tier 3.")
    else:
        print("[llm_meta] GEMINI_API_KEY is not set. Using Tier 3 fallback.")

    # Tier 3: Config and channel topic defaults
    res = fallback_metadata(duration, channel_topic, default_desc, default_tags)
    print(f"[llm_meta] Generated metadata via Tier 3 ({res['path_used']}).")
    return res
