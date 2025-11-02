import re
from urllib.parse import urlparse, urljoin, urldefrag, parse_qsl
from bs4 import BeautifulSoup
from analytics import CrawlerAnalytics

# ---------- Host scope ----------
_ALLOWED_DOMAINS = ("ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu")

def _in_scope_host(host: str) -> bool:
    host = (host or "").lower().strip(".")
    for d in _ALLOWED_DOMAINS:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False


# Initialize analytics (global instance)
analytics = CrawlerAnalytics(stop_words_file="stop_words.txt")

try:
    analytics.save_report(filename="report_progress_restart.txt")
    print("✅ Generated report_progress_restart.txt on startup")
except Exception as e:
    print(f"⚠️ Could not generate initial report: {e}")

# Counter for periodic saves
_page_count = 0
_SAVE_INTERVAL = 100  # Save state every 100 pages

# ---------- Generic regex guards ----------
_REPEAT_SEGMENTS_RE = re.compile(r"/([^/]+/)\1{2,}")
_DATE_PATH_RE = re.compile(r"/(19|20)\d{2}/(0?[1-9]|1[0-2])(/(0?[1-9]|[12]\d|3[01]))?/")
_PAGE_NUM_RE = re.compile(r"/page/\d+/?$", re.I)

# Seminar archive loops (keep – these are common on dept sites)
_SEMINAR_TRAP_RE = re.compile(r"/seminar-series(?:-archive)?(?:/(?:\d{4}-\d{4}))+/?$", re.I)

# Apache/autoindex sort loops
_APACHE_SORT_TRAP_RE = re.compile(r"[?&]C=[A-Z];O=[A-Z]")

# Trac/MediaWiki-style change/history/version/timeline traps
_WIKI_CHANGE_TRAP_RE = re.compile(r"(?:[?&]action=(?:diff|history)\b)|(?:[?&]format=txt\b)|(?:[?&]version=\d+\b)", re.I)
_TRAC_TIMELINE_TRAP_RE = re.compile(r"/timeline\b", re.I)
_TRAC_SECOND_PRECISION_RE = re.compile(r"[?&]from=.*?T.*?(?:%3A|:).*?[&].*precision=second\b", re.I)

# DokuWiki traps (keep since we saw these in logs)
_DOKUWIKI_PATH_RE = re.compile(r"/doku\.php\b|/lib/exe/", re.I)
_DOKUWIKI_QUERY_RE = re.compile(r"[?&](?:do|idx|image|tab_details|ns|id|media|codeblock)=", re.I)

# Disallowed file extensions (expanded to code & plain text blobs)
_DISALLOWED_EXT_RE = re.compile(
    r".*\.(?:css|js|bmp|gif|jpe?g|ico|png|tiff?|mid|mp2|mp3|mp4|wav|avi|mov|mpeg|"
    r"ram|m4v|mkv|ogg|ogv|pdf|ps|eps|tex|pptx?|docx?|xlsx?|names|data|dat|exe|bz2|"
    r"tar|msi|bin|7z|psd|dmg|iso|epub|dll|cnf|tgz|sha1|thmx|mso|arff|rtf|jar|csv|"
    r"rm|smil|wmv|swf|wma|zip|rar|gz|cc|c|h|hpp|cpp|py|java|sh|sql|log|txt)$"
)

# Low-value sections common across CMSes
_LOW_VALUE_PATH_HINTS = (
    "/calendar", "/events", "/event", "/ical", "/wp-json", "/feed", "/tag/", "/author/",
    "/archive", "/archives", "/category/", "/comment", "/reply", "/login", "/signup",
    "/search", "/s/", "/share/", "/print", "/preview", "/api/", "/static/", "/assets/",
    "/cgi-bin/","/videos", "/video", "videos.htm", "video.htm"
)

# Pager & trap query keys
_TRAP_QUERY_KEYS = ("sort", "order", "page", "offset", "limit", "start", "dir", "sessionid", "phpsessid")
_PAGER_KEYS = {"page","p","offset","start","startpage","page_id"}

# Tracking params to drop during normalization
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid","gclid","ref","ref_","source","clid","mc_cid","mc_eid","from","replytocom"}

# Limits
_MAX_URL_LEN = 200
_MAX_QUERY_LEN = 150
_MAX_QUERY_PARAMS = 8
_MAX_PATH_DEPTH = 6

# ---------- Helpers ----------
def _normalize_url(u: str) -> str:
    """Remove tracking params and sort remaining for stability."""
    p = urlparse(u)
    q = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        lk = k.lower()
        if lk in _TRACKING_KEYS or any(lk.startswith(pref) for pref in _TRACKING_PREFIXES):
            continue
        q.append((k, v))
    q.sort(key=lambda kv: kv[0].lower())
    return p._replace(query="&".join(f"{k}={v}" for k, v in q)).geturl()

def _path_depth(path: str) -> int:
    return sum(1 for seg in path.split("/") if seg)

_HTML_OK = (".html", ".htm", ".shtml", ".php", ".asp", ".aspx", ".jsp")
def _looks_htmlish(path: str) -> bool:
    last = path.rsplit("/", 1)[-1]
    if "." not in last:
        return True
    return last.lower().endswith(_HTML_OK)

def _looks_like_action_url(parsed):
    path = parsed.path.lower()
    if any(seg in path for seg in _LOW_VALUE_PATH_HINTS) or _PAGE_NUM_RE.search(path):
        return True
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            lk, lv = k.lower(), (v or "").lower()
            if lk in {"action","do","view","mode","format","print","download","export","media","search"}:
                if lk == "format" and lv in {"diff","print","txt","json","xml","raw","csv"}:
                    return True
                return True
    return False

# ---------- Main API ----------
def scraper(url, resp):
    """Main scraper function called by the crawler"""
    links = extract_next_links(url, resp)
    return [link for link in links if is_valid(link)]

def extract_next_links(url, resp):
    """Extract links and process analytics"""
    global _page_count
    
    links = []
    if not resp or resp.status != 200:
        return links

    raw = getattr(resp, "raw_response", None)
    if raw is None:
        return links

    try:
        ctype = (raw.headers.get("Content-Type", "") or "").lower()
    except Exception:
        ctype = ""

    # strictly require HTML content
    if "html" not in ctype or any(x in ctype for x in ("json", "xml", "octet-stream", "plain")):
        return []

    content = getattr(raw, "content", b"")
    # Check content size (avoid very small stubs and very large files)
    MIN_SIZE = 500  # 500 bytes
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB
    content_size = len(content)
    
    if content_size < MIN_SIZE:
        # Too small - likely stub or redirect
        return []
    
    if content_size > MAX_SIZE:
        # Too large - avoid very large files per assignment requirements
        print(f"[SKIPPED] Large page ({content_size:,} bytes): {url[:80]}")
        return []

    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception:
        return []

    # NEW: Check for actual text content (requirement #5)
    # Remove non-content elements
    for element in soup(["script", "style", "meta", "noscript"]):
        element.decompose()
    
    # Get text and check if it has substance
    text_content = soup.get_text(separator=' ', strip=True)
    if len(text_content) < 100:  # Minimum 100 characters
        # This is a dead page with 200 status but no real content
        return []

    # ========== ANALYTICS PROCESSING ==========
    # Defragment URL for analytics
    defragged_url, _ = urldefrag(url)
    
    # Process page for analytics
    try:
        analytics.process_page(defragged_url, content)
        _page_count += 1
        
        # Periodic status update
        if _page_count % 50 == 0:
            analytics.print_status()
        
        # Periodic save (in case of crash)
        if _page_count % _SAVE_INTERVAL == 0:
            analytics.save_state()
            analytics.save_report(filename=f"report_progress_{_page_count}.txt")
            print(f"Saved analytics state at {_page_count} pages")
    except Exception as e:
        print(f"Error processing analytics for {url}: {e}")
    # ==========================================

    base_url = getattr(raw, "url", None) or resp.url or url

    for tag in soup.find_all("a", href=True):
        # honor rel="nofollow" where present
        rels = tag.get("rel") or []
        if any((r or "").lower() == "nofollow" for r in rels):
            continue

        href = tag.get("href")
        if not href:
            continue

        # Handle malformed URLs gracefully
        try:
            absolute_url = urljoin(base_url, href)
            absolute_url, _ = urldefrag(absolute_url)
            absolute_url = _normalize_url(absolute_url)
            abs_host = urlparse(absolute_url).netloc.lower()
            if not _in_scope_host(abs_host):
                continue
        except (ValueError, Exception):
            # Skip URLs that can't be parsed (malformed, placeholders, etc.)
            continue

        # Skip obvious traps/loops early
        if _APACHE_SORT_TRAP_RE.search(absolute_url):
            continue
        if _WIKI_CHANGE_TRAP_RE.search(absolute_url):
            continue
        if _TRAC_TIMELINE_TRAP_RE.search(absolute_url) and _TRAC_SECOND_PRECISION_RE.search(absolute_url):
            continue

        # Skip direct file-ish downloads before is_valid
        if _DISALLOWED_EXT_RE.match(absolute_url.lower()):
            continue

        links.append(absolute_url)

    # dedupe preserve order
    seen, uniq = set(), []
    for l in links:
        if l not in seen:
            seen.add(l)
            uniq.append(l)
    return uniq
def is_valid(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False

        host = parsed.netloc.lower()
        if not _in_scope_host(host):
            return False

        # length guards
        if len(url) > _MAX_URL_LEN:
            return False

        path_lower = parsed.path.lower()

        # Block genealogy pages (causing 602 errors)
        if '/genealogy/' in path_lower:
            return False

        if '/people/' in path_lower:
            return False

        # Block specific subdomain subpages (allow main page only)
        if 'checkmate.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        if 'kgcs.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        if 'mt-live.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False

        # Block transformativeplay subpages (allow main page)
        if 'transformativeplay.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        
        if 'graphics.ics.uci.edu' in host and '/publications/' in path_lower:
            return False

        if 'grape.ics.uci.edu' in host and '/wiki/public/wiki/' in path_lower:
            return False

        # Block news filter pages (infinite combinations causing 608 errors)
        if '/happening/news/' in path_lower and ('filter[' in parsed.query.lower() or 'filter%5B' in parsed.query.lower()):
            return False

        # Block ~goodrich/teach lab manuals (causing 602 errors)
        if '/~goodrich/teach/' in path_lower and '/labmanual/' in path_lower:
            return False
        
        # Block fano.ics.uci.edu entirely (all CA rules return 601)
        if 'fano.ics.uci.edu' in host:
            return False
        # Block sli.ics.uci.edu extras and classes (causing 601 errors)
        if 'sli.ics.uci.edu' in host and ('/extras/' in path_lower or '/classes/' in path_lower):
            return False

        # Block ~jutts course materials (causing 602 errors)
        if '/~jutts/' in path_lower:
            return False

        # Block ~dechter courses (causing 602 errors)  
        if '/~dechter/courses/' in path_lower:
            return False

        # Block cypress subpages (causing 602 errors, but allow main page)
        if '/~dsm/cypress/' in path_lower:
            return False

        
        # Block source code repositories and build directories
        if "physics.uci.edu/~outreach/demos" in url.lower():
            return False
        
        # Only block if /src/ or /build/ appear (code repos)
        # But allow /docs/ for documentation sites
        if any(x in path_lower for x in ['/src/', '/build/', '/lib/', '/bin/']):
            return False

        # Block /releases/ only if it looks like software releases
        if '/releases/' in path_lower and any(x in path_lower for x in ['/src/', '/build/', 'download']):
            return False
                
        # Only block deep course material paths that cause issues
        # Allow top-level course pages
        if re.match(r"^/~[^/]+/(ics|cs|inf)\d+/.+/.+/", path_lower):
            # Blocks /~prof/ics32/lectures/week1/code/examples/ (deep nesting)
            # Allows /~prof/ics32/ and /~prof/ics32/syllabus (top level)
            return False

        # Block makefile and README files
        if path_lower.endswith(('makefile', 'readme', '/readme', '/makefile')):
            return False

        # Block photo/image galleries 
        if any(x in path_lower for x in ['/pix/', '/images/', '/gallery/', '/photos/', 
                                          '/img/', '/pics/', '/picture/']):
            return False
        
        # Video trap
        if path_lower.startswith("/~projects/cert/safire/meetings/"):
            return False
    
        # Block attachment pages
        if '/attachment/' in path_lower:
            return False
        
        # Block WordPress uploads
        if "/wp-content/uploads/" in path_lower:
            return False
        
        # Block ALL seminar-series with years
        if "/seminar-series" in path_lower and re.search(r'\d{4}-\d{4}', path_lower):
            return False
        
        # Block nested seminar paths
        if path_lower.count("/seminar-series") > 1:
            return False
        
        if path_lower.endswith("/wp-login.php") or "/wp-admin" in path_lower:
            return False
        if "redirect_to=" in parsed.query.lower():
            return False

        # Generic loop & action traps
        if _looks_like_action_url(parsed):
            return False

        # Specific traps (seen in your logs)
        if _WIKI_CHANGE_TRAP_RE.search(url):
            return False
        if _TRAC_TIMELINE_TRAP_RE.search(path_lower) and _TRAC_SECOND_PRECISION_RE.search(url):
            return False
        if _SEMINAR_TRAP_RE.search(path_lower):
            return False
        if _APACHE_SORT_TRAP_RE.search(url):
            return False
        if _DOKUWIKI_PATH_RE.search(path_lower) or _DOKUWIKI_QUERY_RE.search(url):
            return False

        # structural loops
        if _REPEAT_SEGMENTS_RE.search(path_lower + ("/" if not path_lower.endswith("/") else "")):
            return False
        if _DATE_PATH_RE.search(path_lower):
            return False
        if _PAGE_NUM_RE.search(path_lower):
            return False

        # path depth & fanout cap
        if _path_depth(parsed.path) > _MAX_PATH_DEPTH:
            return False

        # query explosion guards
        if parsed.query:
            if len(parsed.query) > _MAX_QUERY_LEN:
                return False
            params = parse_qsl(parsed.query, keep_blank_values=True)
            if len(params) > _MAX_QUERY_PARAMS:
                return False
            for k, v in params:
                lk = k.lower()
                if lk in _TRAP_QUERY_KEYS and v.isdigit() and int(v) > 50:
                    return False
                if lk in _PAGER_KEYS and v.isdigit() and int(v) > 50:
                    return False

        # prefer html-ish paths (if no query)
        if not parsed.query and not _looks_htmlish(parsed.path):
            return False

        # final disallowed-extension gate (covers files even with queries)
        if _DISALLOWED_EXT_RE.match(parsed.path.lower()):
            return False

        return True

    except TypeError:
        print("TypeError for ", url)
        raise
    except Exception:
        return False

def get_analytics():
    """Expose analytics object for final report generation"""
    return analytics
