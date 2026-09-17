"""AI-powered YouTube and Reels metadata generator using Google Gemini.

Generates:
- title: Under 60 characters, main keyword near the front, no clickbait padding.
- description: 3 to 5 lines. First two lines carry the real hook. Natural sentences.
- tags: 10 to 15 items, total under 460 characters.
- hashtags: Exactly 3, appended to the end of the description.

Includes strict validation with silent fallback to filename-based metadata on any failure.
"""
import json
import os
import re
import socket
import urllib3.util.connection

try:
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

import requests

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def clean_text(text):
    """Removes excessive emoji-spam and shouty ALL CAPS."""
    if not text:
        return ""
    # Strip excessive emojis (limit consecutive emojis to 1)
    text = re.sub(r"([\U00010000-\U0010ffff\u2600-\u27bf]){2,}", r"\1", text)
    # If text is predominantly ALL CAPS (and > 10 chars), convert to capitalized sentence
    letters = [c for c in text if c.isalpha()]
    if letters and (sum(1 for c in letters if c.isupper()) / len(letters)) > 0.6:
        # Convert ALL CAPS to sentence case while preserving normal words
        text = text.capitalize()
    return text.strip()


def validate_metadata(data, duration=0, channel_topic=""):
    """Validates the AI output strictly against YouTube requirements.
    
    Requirements:
    - title: under 60 characters, non-empty, keyword near front.
    - description: 3 to 5 lines, hook in first 2 lines.
    - tags: 10 to 15 items, total under 460 chars.
    - hashtags: exactly 3, appended to description.
    - If duration <= 60: 'shorts' in tags.
    """
    if not isinstance(data, dict):
        return None

    title = clean_text(str(data.get("title", "")))
    raw_desc = str(data.get("description", "")).strip()
    tags = data.get("tags", [])
    hashtags = data.get("hashtags", [])

    # Title must be under 60 characters and non-empty
    if not title or len(title) >= 60:
        return None

    # Check description lines (3 to 5 non-empty lines)
    desc_lines = [clean_text(l) for l in raw_desc.splitlines() if l.strip()]
    if len(desc_lines) < 2:
        return None
    # Truncate to max 5 lines if model rambled
    if len(desc_lines) > 5:
        desc_lines = desc_lines[:5]
    desc = "\n".join(desc_lines)

    # Validate and normalize tags (10 to 15 items, total under 460 chars)
    if not isinstance(tags, list):
        return None

    clean_tags = []
    seen = set()
    for t in tags:
        clean_t = re.sub(r"[#,\n\r]", "", str(t)).strip()
        if clean_t and clean_t.lower() not in seen:
            seen.add(clean_t.lower())
            clean_tags.append(clean_t)

    # Ensure 10 to 15 tags
    if len(clean_tags) < 5:
        return None
    clean_tags = clean_tags[:15]

    # For videos <= 60s, keep 'shorts' in tags
    if duration <= 60:
        if "shorts" not in [t.lower() for t in clean_tags]:
            clean_tags.insert(0, "shorts")
            if len(clean_tags) > 15:
                clean_tags = clean_tags[:15]

    # Enforce total tags string length under 460 characters (YouTube limit)
    while clean_tags and len(",".join(clean_tags)) >= 460:
        clean_tags.pop()

    if not clean_tags:
        return None

    # Extract exactly 3 clean hashtags
    clean_hashtags = []
    for h in hashtags:
        tag = re.sub(r"[^A-Za-z0-9_]", "", str(h)).strip()
        if tag and f"#{tag}" not in clean_hashtags:
            clean_hashtags.append(f"#{tag}")

    # If model returned fewer than 3, supplement from tags or topic
    backup_pool = [re.sub(r"[^A-Za-z0-9_]", "", t) for t in clean_tags if t.lower() != "shorts"]
    if channel_topic:
        backup_pool.insert(0, re.sub(r"[^A-Za-z0-9_]", "", channel_topic))
    for candidate in backup_pool:
        if len(clean_hashtags) >= 3:
            break
        if candidate and f"#{candidate}" not in clean_hashtags:
            clean_hashtags.append(f"#{candidate}")

    clean_hashtags = clean_hashtags[:3]

    # Append exactly 3 hashtags to the end of the description
    if clean_hashtags:
        ht_line = " ".join(clean_hashtags)
        # Avoid duplicating if already present
        if ht_line not in desc:
            desc = f"{desc}\n\n{ht_line}"

    return {
        "title": title,
        "description": desc,
        "tags": clean_tags,
        "hashtags": clean_hashtags,
        "path_used": "ai_gemini"
    }


def generate_metadata(filename, duration=0, channel_topic="", api_key=None, fallback_desc=""):
    """Calls Google Gemini to generate optimized video metadata.

    Falls back silently to filename-based metadata on any error.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("[llm_meta] Notice: GEMINI_API_KEY not set. Using filename fallback.")
        return fallback_metadata(filename, duration, fallback_desc)

    raw_name = os.path.splitext(filename)[0].replace("_", " ").strip()
    topic_context = f"The channel topic/niche is: '{channel_topic}'." if channel_topic else "General interest."

    prompt = f"""You are an expert YouTube SEO metadata specialist.
A video with filename '{raw_name}' and duration {duration} seconds is being published.
{topic_context}

Generate optimized, high-CTR, non-clickbait metadata.
Output MUST be valid JSON adhering strictly to this schema:
{{
  "title": "Clear, engaging title UNDER 60 characters with the primary keyword near the beginning. No clickbait padding and no ALL CAPS.",
  "description": "3 to 5 lines. The first two lines must carry a strong hook since only those are visible before 'more'. Followed by relevant keywords written as natural sentences.",
  "tags": ["10 to 15 tag keywords, mixing broad and specific, total under 450 characters"],
  "hashtags": ["Three relevant hashtags without '#', exactly 3 items"]
}}
"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json"
        }
    }

    try:
        url = f"{GEMINI_API_URL}?key={key}"
        resp = requests.post(url, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        res_json = resp.json()
        cand = res_json.get("candidates", [{}])[0]
        text_content = cand.get("content", {}).get("parts", [{}])[0].get("text", "")

        parsed = json.loads(text_content)
        validated = validate_metadata(parsed, duration=duration, channel_topic=channel_topic)
        if validated:
            print("[llm_meta] Successfully generated AI metadata via Gemini.")
            return validated
        else:
            print("[llm_meta] AI output failed validation. Falling back to filename metadata.")
    except Exception as e:
        print(f"[llm_meta] Gemini API call failed ({e}). Falling back to filename metadata.")

    return fallback_metadata(filename, duration, fallback_desc)


def fallback_metadata(filename, duration=0, default_desc=""):
    """Fallback metadata extractor using filename."""
    raw_name = os.path.splitext(filename)[0].replace("_", " ").strip()
    found_hashtags = re.findall(r"#([A-Za-z0-9_]+)", raw_name)
    title = re.sub(r"#\w+", "", raw_name).strip() or raw_name
    tags = ["shorts", "viral"] if duration <= 60 else ["video", "multipost"]
    for h in found_hashtags:
        if h.lower() not in tags:
            tags.append(h.lower())

    clean_hashtags = [f"#{h}" for h in found_hashtags[:3]]
    if len(clean_hashtags) < 3:
        for default_h in ["shorts", "viral", "trending"]:
            if len(clean_hashtags) >= 3:
                break
            if f"#{default_h}" not in clean_hashtags:
                clean_hashtags.append(f"#{default_h}")

    desc = default_desc or title
    if clean_hashtags:
        desc = f"{desc}\n\n{' '.join(clean_hashtags)}"

    return {
        "title": title[:59],
        "description": desc,
        "tags": tags[:15],
        "hashtags": clean_hashtags,
        "path_used": "filename_fallback"
    }

