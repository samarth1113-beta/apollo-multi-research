"""
Pure Python Source Credibility Scoring (backend/tools/source_scoring.py).
Follows exact rules from APOLLO_SPEC.md:
- Start at 50
- .gov, .gov.in, .nic.in, .edu, .ac.in, or who.int, worldbank.org, un.org, imf.org, rbi.org.in, pib.gov.in: +35
- arxiv.org, nature.com, sciencedirect.com, springer.com, ieee.org, nih.gov, pubmed: +30
- Reputed news (reuters.com, thehindu.com, indianexpress.com, livemint.com, economictimes.indiatimes.com,
  bbc.com, hindustantimes.com, downtoearth.org.in, business-standard.com): +20
- wikipedia.org: +10
- medium.com, blogspot.com, wordpress.com, quora.com, reddit.com: -10
- Unknown domain with very short content (under 300 chars): -15
- Published in last 2 years: +10. Older than 5 years: -10. Unknown date: 0.
- Clamp to 0 to 100. Badge: High 70+, Medium 50 to 69, Low 35 to 49, Dropped below 35.
- Return {score, badge, reasons: [list of short strings explaining the score]}.
"""
from datetime import datetime
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


GOV_EDU_SUFFIXES = (
    ".gov",
    ".gov.in",
    ".nic.in",
    ".edu",
    ".ac.in",
)

GOV_INTL_DOMAINS = {
    "who.int",
    "worldbank.org",
    "un.org",
    "imf.org",
    "rbi.org.in",
    "pib.gov.in",
}

ACADEMIC_DOMAINS = {
    "arxiv.org",
    "nature.com",
    "sciencedirect.com",
    "springer.com",
    "ieee.org",
    "nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
}

REPUTED_NEWS_DOMAINS = {
    "reuters.com",
    "thehindu.com",
    "indianexpress.com",
    "livemint.com",
    "economictimes.indiatimes.com",
    "bbc.com",
    "bbc.co.uk",
    "hindustantimes.com",
    "downtoearth.org.in",
    "business-standard.com",
}

BLOG_SOCIAL_DOMAINS = {
    "medium.com",
    "blogspot.com",
    "wordpress.com",
    "quora.com",
    "reddit.com",
}

DOMESTIC_USER_OPINION_DOMAINS = {
    "reddit.com",
    "quora.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
}

DOMESTIC_RETAIL_DOMAINS = {
    "amazon.in",
    "amazon.com",
    "flipkart.com",
}

DOMESTIC_TRUSTED_REVIEW_DOMAINS = {
    "gsmarena.com",
    "91mobiles.com",
    "smartprix.com",
    "digit.in",
    "rtings.com",
    "notebookcheck.net",
    "theverge.com",
    "techradar.com",
}


def extract_domain(url: str) -> str:
    """Extract normalized lowercase hostname without leading 'www.' from a URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().strip()
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _domain_matches(domain: str, target_set: set) -> bool:
    """Check if domain equals or is a subdomain of any domain in target_set."""
    if not domain:
        return False
    for target in target_set:
        if domain == target or domain.endswith("." + target):
            return True
    return False


def _extract_year(published_date: Optional[str], content: str = "", url: str = "") -> Optional[int]:
    """
    Extract a 4-digit publication year from published_date (or fallback to URL).
    Returns None if unknown.
    """
    current_year = datetime.now().year
    for candidate in (published_date or "", url or ""):
        if not candidate:
            continue
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(candidate))
        if match:
            year = int(match.group(1))
            if 1950 <= year <= current_year + 1:
                return year
    return None


def score_source(source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute credibility score (0-100), quality badge, and human-readable reasons
    for a source dictionary.
    """
    score = 50
    reasons: List[str] = ["Base score: 50"]

    url = source.get("url", "")
    domain = (source.get("domain") or extract_domain(url)).lower()
    content = source.get("content") or ""
    published_date = source.get("published_date")

    known_domain = False

    # 1. Domain category checks
    if domain.endswith(GOV_EDU_SUFFIXES) or _domain_matches(domain, GOV_INTL_DOMAINS):
        score += 35
        known_domain = True
        reasons.append(f"Official government/academic/international domain ({domain}): +35")
    elif (
        _domain_matches(domain, ACADEMIC_DOMAINS)
        or "pubmed" in domain
    ):
        score += 30
        known_domain = True
        reasons.append(f"Peer-reviewed/scientific repository ({domain}): +30")
    elif _domain_matches(domain, REPUTED_NEWS_DOMAINS):
        score += 20
        known_domain = True
        reasons.append(f"Reputed news organization ({domain}): +20")
    elif _domain_matches(domain, {"wikipedia.org"}):
        score += 10
        known_domain = True
        reasons.append("Wikipedia reference domain: +10")
    elif _domain_matches(domain, BLOG_SOCIAL_DOMAINS):
        score -= 10
        known_domain = True
        reasons.append(f"User-generated blog/forum ({domain}): -10")

    # 2. Unknown domain with very short content (< 300 chars)
    if not known_domain and len(content.strip()) < 300:
        score -= 15
        reasons.append("Unknown domain with short content (<300 chars): -15")

    # 3. Publication date recency check
    pub_year = _extract_year(published_date, content, url)
    current_year = datetime.now().year
    if pub_year is not None:
        age = max(0, current_year - pub_year)
        if age <= 2:
            score += 10
            reasons.append(f"Published recently ({pub_year}, within last 2 years): +10")
        elif age > 5:
            score -= 10
            reasons.append(f"Older publication ({pub_year}, >5 years old): -10")
        else:
            reasons.append(f"Published in {pub_year} (2-5 years old): +0")
    else:
        reasons.append("Publication date unknown: +0")

    # 4. Clamp to 0..100
    score = max(0, min(100, score))

    # 5. Assign badge
    if score >= 70:
        badge = "High"
    elif score >= 50:
        badge = "Medium"
    elif score >= 35:
        badge = "Low"
    else:
        badge = "Dropped"

    return {
        "score": score,
        "badge": badge,
        "reasons": reasons,
    }


def score_domestic_source(source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure Python credibility scoring for Domestic (consumer/product) runs:
    - Start at 55.
    - reddit.com, quora.com, youtube.com, x.com: +5 (real user voices are wanted here).
    - amazon.in, flipkart.com: +10.
    - Trusted review sites (gsmarena.com, 91mobiles.com, smartprix.com, digit.in,
      rtings.com, notebookcheck.net, theverge.com, techradar.com): +20.
    - Content under 200 chars: -15.
    - Published in the last year: +10, older than 3 years: -15.
    - Tag each source as "User opinion", "Retail", or "Expert review".
    """
    score = 55
    reasons: List[str] = ["Domestic base score: 55"]

    url = source.get("url", "")
    domain = (source.get("domain") or extract_domain(url)).lower()
    content = source.get("content") or ""
    published_date = source.get("published_date")
    platform = (source.get("platform") or "").strip()

    # 1. Domain & source_type classification
    if _domain_matches(domain, DOMESTIC_USER_OPINION_DOMAINS) or platform in (
        "Reddit",
        "X",
        "Quora",
        "YouTube",
    ):
        score += 5
        source_type = "User opinion"
        reasons.append(f"Real user opinion platform ({domain or platform}): +5")
    elif _domain_matches(domain, DOMESTIC_RETAIL_DOMAINS) or platform in (
        "Amazon",
        "Flipkart",
    ):
        score += 10
        source_type = "Retail"
        reasons.append(f"Retail store listing ({domain or platform}): +10")
    elif _domain_matches(domain, DOMESTIC_TRUSTED_REVIEW_DOMAINS):
        score += 20
        source_type = "Expert review"
        reasons.append(f"Trusted product review site ({domain}): +20")
    else:
        source_type = "Expert review"
        reasons.append(f"General web/review source ({domain}): +0")

    # 2. Content length check (< 200 chars: -15)
    if len(content.strip()) < 200:
        score -= 15
        reasons.append("Short content (<200 chars): -15")

    # 3. Publication date recency check (last year: +10, older than 3 years: -15)
    pub_year = _extract_year(published_date, content, url)
    current_year = datetime.now().year
    if pub_year is not None:
        age = max(0, current_year - pub_year)
        if age <= 1:
            score += 10
            reasons.append(f"Published within the last year ({pub_year}): +10")
        elif age > 3:
            score -= 15
            reasons.append(f"Older than 3 years ({pub_year}): -15")
        else:
            reasons.append(f"Published in {pub_year} (2-3 years old): +0")
    else:
        reasons.append("Publication date unknown: +0")

    # 4. Clamp to 0..100
    score = max(0, min(100, score))

    # 5. Assign badge
    if score >= 70:
        badge = "High"
    elif score >= 50:
        badge = "Medium"
    elif score >= 35:
        badge = "Low"
    else:
        badge = "Dropped"

    return {
        "score": score,
        "badge": badge,
        "reasons": reasons,
        "source_type": source_type,
    }
