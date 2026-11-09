"""
Reddit Feed Parser module.
Fetches and parses video posts from subreddits via Reddit's Atom/RSS feeds.
No API keys or OAuth required.
"""
import os
import re
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Set, Optional
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

from src.config import (
    DEFAULT_REDDIT_SUBREDDITS,
    REDDIT_SEEN_POSTS_FILE,
    logger
)

# Standard desktop User-Agent to avoid blocks on Reddit public endpoints
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# Known video domains and patterns
VIDEO_URL_PATTERNS = [
    re.compile(r'https?://(?:www\.)?redgifs\.com/(?:watch|ifr)/[a-zA-Z0-9]+', re.IGNORECASE),
    re.compile(r'https?://v\.redd\.it/[a-zA-Z0-9]+', re.IGNORECASE),
    re.compile(r'https?://(?:www\.)?streamable\.com/[a-zA-Z0-9]+', re.IGNORECASE),
    re.compile(r'https?://i\.imgur\.com/[a-zA-Z0-9]+\.(?:mp4|gifv|webm)', re.IGNORECASE),
    re.compile(r'https?://[^\s"\'<>]+\.(?:mp4|webm|mkv|mov)(?:\?[^\s"\'<>]*)?', re.IGNORECASE),
]

ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}


def normalize_subreddit(sub_or_url: str) -> str:
    """
    Extract clean subreddit name from URL or shorthand.
    Examples:
        'https://www.reddit.com/r/tits/' -> 'tits'
        'r/boobs' -> 'boobs'
        'amazingtits' -> 'amazingtits'
    """
    if not sub_or_url:
        return ''
    cleaned = sub_or_url.strip().rstrip('/')
    if '/r/' in cleaned:
        cleaned = cleaned.split('/r/')[-1]
    elif cleaned.startswith('r/'):
        cleaned = cleaned[2:]
    return cleaned.split('/')[0].strip()


def extract_video_url(content_html: str, permalink: str = '') -> Optional[str]:
    """
    Extract direct video URL from Reddit RSS HTML content.
    Prefers redgifs/v.redd.it/direct mp4 URLs.
    """
    if not content_html:
        return None

    hrefs = re.findall(r'href="([^"]+)"', content_html)
    for href in hrefs:
        # Ignore Reddit user profiles or internal comments navigation
        if 'reddit.com/user/' in href or 'reddit.com/u/' in href:
            continue
        for pattern in VIDEO_URL_PATTERNS:
            if pattern.search(href):
                # Clean up .gifv to .mp4 for Imgur
                if href.endswith('.gifv'):
                    href = href[:-5] + '.mp4'
                return href

    # If permalink points directly to v.redd.it or similar
    if permalink and any(p.search(permalink) for p in VIDEO_URL_PATTERNS):
        return permalink

    return None


def parse_atom_entries(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse Atom XML feed into structured post dictionaries.
    """
    posts = []
    try:
        root = ET.fromstring(xml_bytes)
        for entry in root.findall('atom:entry', ATOM_NS):
            id_elem = entry.find('atom:id', ATOM_NS)
            title_elem = entry.find('atom:title', ATOM_NS)
            link_elem = entry.find('atom:link', ATOM_NS)
            content_elem = entry.find('atom:content', ATOM_NS)
            updated_elem = entry.find('atom:updated', ATOM_NS)

            post_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ''
            # Strip Reddit prefix 't3_' if present for cleaner IDs
            if post_id.startswith('t3_'):
                post_id = post_id[3:]

            title = title_elem.text.strip() if title_elem is not None and title_elem.text else 'Untitled'
            permalink = link_elem.attrib.get('href', '') if link_elem is not None else ''
            content_html = content_elem.text if content_elem is not None and content_elem.text else ''
            updated_str = updated_elem.text if updated_elem is not None else ''

            # Extract video URL
            video_url = extract_video_url(content_html, permalink)

            if post_id and video_url:
                posts.append({
                    'id': post_id,
                    'title': title,
                    'permalink': permalink,
                    'video_url': video_url,
                    'updated': updated_str
                })
    except Exception as e:
        logger.error(f"Error parsing Atom XML: {e}")

    return posts


def fetch_subreddit_posts(
    subreddits: Optional[List[str]] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 15
) -> List[Dict[str, Any]]:
    """
    Fetch new posts from subreddits.
    Attempts combined multi-sub query first, falls back to individual subreddits.

    Args:
        subreddits: List of subreddit names or URLs
        user_agent: HTTP User-Agent
        timeout: Request timeout in seconds

    Returns:
        List[Dict[str, Any]]: List of video post dictionaries
    """
    subs = subreddits or DEFAULT_REDDIT_SUBREDDITS
    clean_subs = [normalize_subreddit(s) for s in subs if normalize_subreddit(s)]
    if not clean_subs:
        logger.warning("No valid subreddits provided to fetch.")
        return []

    headers = {'User-Agent': user_agent}

    # Strategy 1: Combined multi-sub query in one request
    multi_sub_path = '+'.join(clean_subs)
    combined_url = f"https://www.reddit.com/r/{multi_sub_path}/new.rss"
    try:
        r = requests.get(combined_url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            posts = parse_atom_entries(r.content)
            logger.info(f"Fetched {len(posts)} video posts from combined feed r/{multi_sub_path}")
            return posts
        else:
            logger.warning(f"Combined feed returned HTTP {r.status_code}, falling back to single subreddits")
    except Exception as e:
        logger.warning(f"Failed fetching combined feed: {e}, falling back to individual feeds")

    # Strategy 2: Individual subreddit queries with delay to prevent 429
    all_posts = []
    seen_ids = set()

    for sub in clean_subs:
        url = f"https://www.reddit.com/r/{sub}/new.rss"
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                posts = parse_atom_entries(r.content)
                for p in posts:
                    if p['id'] not in seen_ids:
                        seen_ids.add(p['id'])
                        p['subreddit'] = sub
                        all_posts.append(p)
                logger.info(f"Fetched {len(posts)} video posts from r/{sub}")
            else:
                logger.warning(f"r/{sub} returned HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"Error fetching r/{sub}: {e}")

        # Sleep between requests to avoid rate limit
        time.sleep(2)

    return all_posts


def load_seen_posts(file_path: str = REDDIT_SEEN_POSTS_FILE) -> Set[str]:
    """
    Load set of previously seen Reddit post IDs.
    """
    if not os.path.exists(file_path):
        return set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
            elif isinstance(data, dict):
                return set(data.get('seen_ids', []))
    except Exception as e:
        logger.warning(f"Could not load seen posts from {file_path}: {e}")
    return set()


def save_seen_posts(seen_ids: Set[str], file_path: str = REDDIT_SEEN_POSTS_FILE):
    """
    Persist set of seen Reddit post IDs.
    Keeps the most recent 5,000 IDs to avoid unbounded file growth.
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    # Keep up to 5000 IDs
    ids_list = list(seen_ids)[-5000:]
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({'seen_ids': ids_list, 'updated_at': datetime.now().isoformat()}, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save seen posts to {file_path}: {e}")


def filter_new_posts(
    posts: List[Dict[str, Any]],
    seen_ids: Set[str]
) -> List[Dict[str, Any]]:
    """
    Filter out already-seen posts from the list of fetched posts.
    """
    return [p for p in posts if p.get('id') and p['id'] not in seen_ids]
