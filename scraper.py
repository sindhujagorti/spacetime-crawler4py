import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, urldefrag, urlparse, urlunparse

def scraper(url, resp):
    links = extract_next_links(url, resp)
    return [link for link in links if is_valid(link)]

def extract_next_links(url, resp):
    links = []

    # Validate the response
    if not resp or resp.status != 200:
        return links

    raw = getattr(resp, "raw_response", None)
    if raw is None or not hasattr(raw, "content"):
        return links
    content = raw.content
    if not content:
        return links

    # Verify this is HTML (not a binary file)
    try:
        ctype = raw.headers.get("Content-Type", "") or ""
    except Exception:
        ctype = ""
    if "html" not in ctype.lower():
        # simple binary sniff fallback
        if b"<" not in content[:1000]:
            return links

    base_url = getattr(raw, "url", None) or getattr(resp, "url", None) or url

    try:
        soup = BeautifulSoup(content, "lxml")
    except Exception:
        soup = BeautifulSoup(content, "html.parser")

    candidates = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if not href:
            continue
        # Skip non-http schemes
        if href.startswith(("mailto:", "javascript:", "tel:", "data:")):
            continue
        abs_url = urljoin(base_url, href)
        abs_url, _ = urldefrag(abs_url)  # remove fragments
        candidates.append(abs_url)

    seen = set()
    for link in candidates:
        if link not in seen:
            seen.add(link)
            links.append(link)

    return links


def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        parsed = urlparse(url)
        if parsed.scheme not in set(["http", "https"]):
            return False
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())

    except TypeError:
        print ("TypeError for ", parsed)
        raise
