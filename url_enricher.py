"""
url_enricher.py
Handles URL fetching, HTML parsing, and feature extraction.
"""
import requests
from bs4 import BeautifulSoup
import time
import json
import logging

from title_patterns import PATTERNS as _TITLE_PATTERNS

# Question-shaped heading detection reuses the shared title-pattern regexes
# so the definition of "question" is single-sourced (Spec: seo_geo_review T.2).
_QUESTION_PATTERN_NAMES = {"question", "how_to", "what_is"}
_QUESTION_REGEXES = [
    regex for name, regex in _TITLE_PATTERNS if name in _QUESTION_PATTERN_NAMES
]


def _is_question_shaped(text):
    return any(regex.search(text) for regex in _QUESTION_REGEXES)


class UrlEnricher:
    def __init__(self, user_agent="MarketIntelligenceBot/1.0", timeout=10):
        self.headers = {'User-Agent': user_agent}
        self.timeout = timeout

    def fetch_url(self, url):
        """
        Fetches URL and returns response object.
        Tries HEAD first, then GET if content-type is HTML.
        """
        try:
            # Try HEAD first to check content type
            try:
                head_resp = requests.head(
                    url, headers=self.headers, timeout=self.timeout, allow_redirects=True)
                content_type = head_resp.headers.get(
                    'Content-Type', '').lower()

                # If PDF, don't download body
                if 'application/pdf' in content_type:
                    return {
                        'url': url,
                        'status_code': head_resp.status_code,
                        'headers': dict(head_resp.headers),
                        'content': None,
                        'is_pdf': True
                    }
            except requests.RequestException:
                pass  # Fallback to GET if HEAD fails (some servers block HEAD)

            # GET request
            response = requests.get(
                url, headers=self.headers, timeout=self.timeout)
            return {
                'url': url,
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'content': response.content,
                'is_pdf': False
            }
        except Exception as e:
            logging.warning(f"Error fetching {url}: {e}")
            return None

    def extract_features(self, fetch_result):
        """
        Parses HTML content and extracts features.
        """
        if not fetch_result:
            return {}

        if fetch_result.get('is_pdf'):
            return {
                'soup': None,
                'word_count_est': 0,
                'h1_count': 0,
                'h2_count': 0,
                'title_length': 0,
                'meta_desc_length': 0,
                'schema_types': [],
                'faq_present': False,
                'question_heading_count': 0,
                'question_headings': [],
                'intro_text_length': 0,
                'published_time': None,
                'modified_time': None
            }

        if not fetch_result.get('content'):
            return {}

        try:
            soup = BeautifulSoup(fetch_result['content'], 'html.parser')
        except Exception:
            return {}

        # Basic Text Stats
        text = soup.get_text(" ", strip=True)
        word_count = len(text.split())

        # Headings
        h1_count = len(soup.find_all('h1'))
        h2_count = len(soup.find_all('h2'))

        # Answer-extractability signals (Spec: seo_geo_review_20260704.md
        # T.2): AI answer engines favor pages whose section headings are the
        # question in the searcher's words and whose answer starts
        # immediately. Question-shape detection reuses the title_patterns
        # regexes (question / how_to / what_is) so "what counts as a
        # question" has one definition in the codebase.
        question_headings = []
        for heading in soup.find_all(['h2', 'h3']):
            heading_text = heading.get_text(" ", strip=True)
            if heading_text and _is_question_shaped(heading_text):
                question_headings.append(heading_text)
        # Length of body text before the first H2 — a long intro means any
        # answer is buried below warm-up prose.
        first_h2 = soup.find('h2')
        if first_h2 is not None:
            intro_text_length = sum(
                len(p.get_text(" ", strip=True))
                for p in first_h2.find_all_previous('p')
            )
        else:
            intro_text_length = len(text)

        # Meta
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_desc_tag = soup.find('meta', attrs={'name': 'description'})
        meta_desc = meta_desc_tag['content'].strip(
        ) if meta_desc_tag and meta_desc_tag.get('content') else ""

        # Schema Extraction — parse each JSON-LD block once, then feed the
        # parsed data to type extraction and date extraction.
        schema_types = set()
        json_ld_blocks = []
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                except json.JSONDecodeError:
                    continue
                json_ld_blocks.append(data)
                self._extract_schema_types(data, schema_types)

        # Content freshness (Spec: seo_geo_deferred_spec_v1.md#G.6):
        # best-effort published/modified timestamps, raw ISO strings or
        # None. Priority per field: article:* meta tags, then JSON-LD
        # datePublished/dateModified, then the first <time datetime=...>
        # (published only). No NLP date guessing from body text.
        published_time, modified_time = self._extract_dates(
            soup, json_ld_blocks)

        # FAQ Heuristic
        faq_present = False
        if "FAQPage" in schema_types:
            faq_present = True
        else:
            # Simple heuristic: look for "Frequently Asked Questions" text
            if "frequently asked questions" in text.lower():
                faq_present = True

        return {
            'soup': soup,  # Return soup for classifier usage
            'word_count_est': word_count,
            'h1_count': h1_count,
            'h2_count': h2_count,
            'title_length': len(title),
            'meta_desc_length': len(meta_desc),
            'schema_types': list(schema_types),
            'faq_present': faq_present,
            'question_heading_count': len(question_headings),
            'question_headings': question_headings[:10],
            'intro_text_length': intro_text_length,
            'published_time': published_time,
            'modified_time': modified_time
        }

    def _extract_dates(self, soup, json_ld_blocks):
        """Return (published_time, modified_time) as raw strings or None.

        Spec: seo_geo_deferred_spec_v1.md#G.6. Sources, in priority order
        per field: ``article:published_time`` / ``article:modified_time``
        meta tags, JSON-LD ``datePublished`` / ``dateModified``, then the
        first ``<time datetime=...>`` element (published_time only).
        Values are returned verbatim; parsing/validation happens
        downstream in brief_data_extraction (unparseable -> undated).
        """
        published = None
        modified = None

        for prop, current in (("article:published_time", "published"),
                              ("article:modified_time", "modified")):
            tag = soup.find('meta', attrs={'property': prop})
            content = (tag.get('content') or "").strip() if tag else ""
            if content:
                if current == "published":
                    published = content
                else:
                    modified = content

        if published is None or modified is None:
            dates = {}
            for data in json_ld_blocks:
                self._extract_schema_dates(data, dates)
            if published is None:
                published = dates.get("datePublished")
            if modified is None:
                modified = dates.get("dateModified")

        if published is None:
            time_tag = soup.find('time', attrs={'datetime': True})
            if time_tag:
                datetime_attr = (time_tag.get('datetime') or "").strip()
                if datetime_attr:
                    published = datetime_attr

        return published, modified

    def _extract_schema_dates(self, data, dates):
        """Walk parsed JSON-LD collecting the first datePublished/dateModified."""
        if isinstance(data, dict):
            for key in ("datePublished", "dateModified"):
                value = data.get(key)
                if key not in dates and isinstance(value, str) and value.strip():
                    dates[key] = value.strip()
            for v in data.values():
                self._extract_schema_dates(v, dates)
        elif isinstance(data, list):
            for item in data:
                self._extract_schema_dates(item, dates)

    def _extract_schema_types(self, data, type_set):
        if isinstance(data, dict):
            if '@type' in data:
                t = data['@type']
                if isinstance(t, list):
                    type_set.update(t)
                else:
                    type_set.add(t)
            # Recurse
            for v in data.values():
                self._extract_schema_types(v, type_set)
        elif isinstance(data, list):
            for item in data:
                self._extract_schema_types(item, type_set)
