import re
from urllib.parse import urlparse, urljoin, urldefrag, parse_qsl
from bs4 import BeautifulSoup
from analytics import CrawlerAnalytics


# ---------- HOST SCOPE CHECKING ----------

# Allowed domains for crawling
_ALLOWED_DOMAINS = ("ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu")


# ---------- HOST SCOPE CHECKING ----------
# Time Complexity: O(d) where d = number of allowed domains (constant = 4)
# Space Complexity: O(1)
def _in_scope_host(host: str) -> bool:
    # Normalize host: lowercase and remove trailing dots
    # O(h) where h = length of host string
    host = (host or "").lower().strip(".")
    # Check against each allowed domain (O(d) iterations)
    for d in _ALLOWED_DOMAINS:
        d = d.lower()
        # Check exact match OR subdomain match (e.g., "www.ics.uci.edu")
        # O(h) for each comparison
        if host == d or host.endswith("." + d):
            return True
    return False

# ANALYTICS INITIALIZATION

# Initialize analytics (global instance)
analytics = CrawlerAnalytics(stop_words_file="stop_words.txt")

# Counters for periodic state saving
_page_count = 0  # Track number of pages processed
_SAVE_INTERVAL = 100  # Save checkpoint every 100 pages



# REGEX PATTERNS (Compiled once for efficiency)

# Detect repeating path segments: /abc/abc/abc/ (loop indicator)
_REPEAT_SEGMENTS_RE = re.compile(r"/([^/]+/)\1{2,}")

# Detect date-based paths: /2023/12/25/ (calendar traps)
_DATE_PATH_RE = re.compile(r"/(19|20)\d{2}/(0?[1-9]|1[0-2])(/(0?[1-9]|[12]\d|3[01]))?/")

# Detect pagination: /page/5/ (infinite pagination)
_PAGE_NUM_RE = re.compile(r"/page/\d+/?$", re.I)

# Detect seminar archive loops: /seminar-series/2020-2021/2019-2020/...
_SEMINAR_TRAP_RE = re.compile(r"/seminar-series(?:-archive)?(?:/(?:\d{4}-\d{4}))+/?$", re.I)

# Detect Apache directory listing sort parameters: ?C=N;O=A
_APACHE_SORT_TRAP_RE = re.compile(r"[?&]C=[A-Z];O=[A-Z]")

# Detect wiki change/history pages (infinite versions)
_WIKI_CHANGE_TRAP_RE = re.compile(r"(?:[?&]action=(?:diff|history)\b)|(?:[?&]format=txt\b)|(?:[?&]version=\d+\b)", re.I)

# Detect Trac timeline pages with timestamps
_TRAC_TIMELINE_TRAP_RE = re.compile(r"/timeline\b", re.I)
_TRAC_SECOND_PRECISION_RE = re.compile(r"[?&]from=.*?T.*?(?:%3A|:).*?[&].*precision=second\b", re.I)

# Detect DokuWiki paths and query parameters
_DOKUWIKI_PATH_RE = re.compile(r"/doku\.php\b|/lib/exe/", re.I)
_DOKUWIKI_QUERY_RE = re.compile(r"[?&](?:do|idx|image|tab_details|ns|id|media|codeblock)=", re.I)

# File extensions to skip (not HTML content)
_DISALLOWED_EXT_RE = re.compile(
    r".*\.(?:css|js|bmp|gif|jpe?g|ico|png|tiff?|mid|mp2|mp3|mp4|wav|avi|mov|mpeg|"
    r"ram|m4v|mkv|ogg|ogv|pdf|ps|eps|tex|pptx?|docx?|xlsx?|names|data|dat|exe|bz2|"
    r"tar|msi|bin|7z|psd|dmg|iso|epub|dll|cnf|tgz|sha1|thmx|mso|arff|rtf|jar|csv|"
    r"rm|smil|wmv|swf|wma|zip|rar|gz|cc|c|h|hpp|cpp|py|java|sh|sql|log|txt)$"
)

# Low-value path segments (user actions, not content)
_LOW_VALUE_PATH_HINTS = (
    "/calendar", "/events", "/event", "/ical", "/wp-json", "/feed", "/tag/", "/author/",
    "/archive", "/archives", "/category/", "/comment", "/reply", "/login", "/signup",
    "/search", "/s/", "/share/", "/print", "/preview", "/api/", "/static/", "/assets/",
    "/cgi-bin/","/videos", "/video", "videos.htm", "video.htm"
)

# Query parameters that indicate traps or pagination
_TRAP_QUERY_KEYS = ("sort", "order", "page", "offset", "limit", "start", "dir", "sessionid", "phpsessid")
_PAGER_KEYS = {"page","p","offset","start","startpage","page_id"}

# Tracking parameters to remove during normalization
_TRACKING_PREFIXES = ("utm_",)  # Google Analytics, etc.
_TRACKING_KEYS = {"fbclid","gclid","ref","ref_","source","clid","mc_cid","mc_eid","from","replytocom"}

# URL size limits (prevent memory issues and infinite loops)
_MAX_URL_LEN = 200
_MAX_QUERY_LEN = 150
_MAX_QUERY_PARAMS = 8
_MAX_PATH_DEPTH = 6

# HELPER FUNCTIONS

# Time Complexity: O(p) where p = number of query parameters
# Space Complexity: O(p) for storing filtered parameters
def _normalize_url(u: str) -> str:
    """Remove tracking params and sort remaining for stability."""
    # Parse URL into components: O(n) where n = URL length
    p = urlparse(u)

    # Process query parameters
    q = []  # Filtered query params list
    
    # Parse query string into key-value pairs: O(q) where q = query length
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        lk = k.lower()  # Normalize key for comparison: O(len(k))
        
        # Skip tracking parameters (analytics, social media, etc.)
        # O(t) where t = number of tracking keys/prefixes (constant)
        if lk in _TRACKING_KEYS or any(lk.startswith(pref) for pref in _TRACKING_PREFIXES):
            continue
        
        # Keep legitimate parameters
        q.append((k, v))
    
    # Sort parameters alphabetically for consistent URLs: O(p log p)
    # Makes url?b=2&a=1 equivalent to url?a=1&b=2
    q.sort(key=lambda kv: kv[0].lower())
    
    # Reconstruct URL with normalized query: O(p)
    return p._replace(query="&".join(f"{k}={v}" for k, v in q)).geturl()

# Allowed HTML-like file extensions
_HTML_OK = (".html", ".htm", ".shtml", ".php", ".asp", ".aspx", ".jsp")

# Time Complexity: O(1) - constant checks
# Space Complexity: O(1)
def _looks_htmlish(path: str) -> bool:
    """
    Check if a path looks like it could serve HTML content.
    """
    # Get the last path segment (filename): O(n) where n = path length
    last = path.rsplit("/", 1)[-1]
    
    # If no extension, assume it's a page (e.g., /about)
    if "." not in last:
        return True
    
    # Check if it ends with HTML-like extension: O(1) tuple check
    return last.lower().endswith(_HTML_OK)

# Time Complexity: O(p) where p = number of query parameters
# Space Complexity: O(1)
def _looks_like_action_url(parsed):
    """
    Detect URLs that represent actions rather than content pages.
    Examples: search results, print views, export functions, etc.
    """
    path = parsed.path.lower()  # O(n) where n = path length
    
    # Check for low-value path segments: O(h) where h = hints count (constant)
    if any(seg in path for seg in _LOW_VALUE_PATH_HINTS) or _PAGE_NUM_RE.search(path):
        return True
    
    # Check query parameters for action indicators
    if parsed.query:
        # Parse query parameters: O(q) where q = query length
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            lk, lv = k.lower(), (v or "").lower()
            
            # Check if parameter indicates an action
            if lk in {"action","do","view","mode","format","print","download","export","media","search"}:
                # Special handling for format parameter
                if lk == "format" and lv in {"diff","print","txt","json","xml","raw","csv"}:
                    return True
                return True
    return False

# MAIN CRAWLER API

# Time Complexity: O(n * v) where n = number of links, v = validation time per link
# Space Complexity: O(n) for storing valid links
def scraper(url, resp):
    """Main scraper function called by the crawler"""
    links = extract_next_links(url, resp)
    return [link for link in links if is_valid(link)]


# Time Complexity: O(c + l * p) where:
#   c = content parsing time (Beautiful Soup)
#   l = number of links found
#   p = processing time per link
# Space Complexity: O(c + l) for content and links storage
def extract_next_links(url, resp):
    """
    Extract and validate links from an HTTP response.
    Performs analytics processing and link extraction.
    """
    global _page_count  # Access global counter
    
    links = []  # Initialize empty links list
    
    # === RESPONSE VALIDATION ===
    # Check if response exists and is successful: O(1)
    if not resp or resp.status != 200:
        return links
    
    # Get raw HTTP response object: O(1)
    raw = getattr(resp, "raw_response", None)
    if raw is None:
        return links
    
    # === CONTENT-TYPE VALIDATION ===
    # Extract and check Content-Type header: O(1)
    try:
        ctype = (raw.headers.get("Content-Type", "") or "").lower()
    except Exception:
        ctype = ""
    
    # Strictly require HTML content (reject JSON, XML, binary, etc.): O(1)
    if "html" not in ctype or any(x in ctype for x in ("json", "xml", "octet-stream", "plain")):
        return []
    
    # === CONTENT SIZE VALIDATION ===
    # Get page content as bytes: O(1) attribute access
    content = getattr(raw, "content", b"")
    
    # Define size limits to avoid stubs and huge files
    MIN_SIZE = 500  # 500 bytes - minimum meaningful page
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB - prevent memory issues
    content_size = len(content)  # O(1) - just length check
    
    # Reject too-small pages (redirects, stubs): O(1)
    if content_size < MIN_SIZE:
        return []
    
    # Reject too-large pages (downloads, huge documents): O(1)
    if content_size > MAX_SIZE:
        print(f"[SKIPPED] Large page ({content_size:,} bytes): {url[:80]}")
        return []
    
    # === HTML PARSING ===
    # Parse HTML with BeautifulSoup: O(c) where c = content size
    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception:
        return []
    
    # === TEXT CONTENT VALIDATION ===
    # Remove non-content elements (scripts, styles, etc.): O(e) where e = elements
    for element in soup(["script", "style", "meta", "noscript"]):
        element.decompose()  # Remove from DOM
    
    # Extract visible text: O(c)
    text_content = soup.get_text(separator=' ', strip=True)
    
    # Require minimum text content (avoid dead pages): O(1)
    if len(text_content) < 100:  # At least 100 characters
        return []
    
    # === ANALYTICS PROCESSING ===
    # Remove URL fragment for analytics consistency: O(u) where u = URL length
    defragged_url, _ = urldefrag(url)
    
    # Process page for word counting, longest page tracking, etc.
    try:
        # Analytics processing: complexity depends on analytics implementation
        analytics.process_page(defragged_url, content)
        _page_count += 1  # Increment global counter
        
        # Print status every 50 pages: O(1)
        if _page_count % 50 == 0:
            analytics.print_status()
        
        # Save checkpoint every 100 pages (crash recovery): O(s) where s = state size
        if _page_count % _SAVE_INTERVAL == 0:
            analytics.save_state()
            analytics.save_report(filename=f"report_progress_{_page_count}.txt")
            print(f"Saved analytics state at {_page_count} pages")
    except Exception as e:
        print(f"Error processing analytics for {url}: {e}")
    
    # === LINK EXTRACTION ===
    # Get base URL for resolving relative links: O(1)
    base_url = getattr(raw, "url", None) or resp.url or url
    
    # Find all anchor tags with href attributes: O(t) where t = tags in document
    for tag in soup.find_all("a", href=True):
        # === RESPECT NOFOLLOW ===
        # Check if link has rel="nofollow" (SEO hint): O(r) where r = rel attributes
        rels = tag.get("rel") or []
        if any((r or "").lower() == "nofollow" for r in rels):
            continue  # Skip this link per webmaster request
        
        # Get href value: O(1)
        href = tag.get("href")
        if not href:
            continue
        
        # === URL RESOLUTION & NORMALIZATION ===
        try:
            # Convert relative URL to absolute: O(h) where h = href length
            absolute_url = urljoin(base_url, href)
            
            # Remove fragment (#section): O(u)
            absolute_url, _ = urldefrag(absolute_url)
            
            # Normalize (remove tracking, sort params): O(p) - see _normalize_url
            absolute_url = _normalize_url(absolute_url)
            
            # Extract and validate host: O(u) for parsing
            abs_host = urlparse(absolute_url).netloc.lower()
            
            # Check if host is in scope: O(d) - see _in_scope_host
            if not _in_scope_host(abs_host):
                continue  # Skip external links
                
        except (ValueError, Exception):
            # Skip malformed URLs (invalid syntax, etc.): O(1)
            continue
        
        # === EARLY TRAP DETECTION ===
        # Check for known trap patterns before full validation
        # Each regex search: O(u) where u = URL length
        
        if _APACHE_SORT_TRAP_RE.search(absolute_url):
            continue  # Apache directory sorting infinite loop
        
        if _WIKI_CHANGE_TRAP_RE.search(absolute_url):
            continue  # Wiki history/diff pages
        
        if _TRAC_TIMELINE_TRAP_RE.search(absolute_url) and _TRAC_SECOND_PRECISION_RE.search(absolute_url):
            continue  # Trac timeline with second precision (infinite timestamps)
        
        # Check file extension early: O(u)
        if _DISALLOWED_EXT_RE.match(absolute_url.lower()):
            continue  # Skip direct file downloads
        
        # Add to links list: O(1) amortized
        links.append(absolute_url)
    
    # === DEDUPLICATION ===
    # Remove duplicate links while preserving order: O(l) where l = links count
    seen, uniq = set(), []
    for l in links:
        if l not in seen:  # Set lookup: O(1) average
            seen.add(l)  # Set add: O(1) average
            uniq.append(l)  # List append: O(1) amortized
    
    return uniq


# Time Complexity: O(u + p + r) where:
#   u = URL length for parsing
#   p = query parameters count
#   r = regex pattern matching
# Space Complexity: O(1) - only stores parsed components
def is_valid(url):
    try:
        # === PARSE URL ===
        # Parse URL into components: O(u) where u = URL length
        parsed = urlparse(url)
        
        # === SCHEME VALIDATION ===
        # Only allow HTTP/HTTPS: O(1)
        if parsed.scheme not in {"http", "https"}:
            return False
        
        # === HOST VALIDATION ===
        # Extract and normalize hostname: O(h) where h = host length
        host = parsed.netloc.lower()
        
        # Check if in allowed domains: O(d) - see _in_scope_host
        if not _in_scope_host(host):
            return False
        
        # === LENGTH GUARDS ===
        # Prevent extremely long URLs (often generated loops): O(1)
        if len(url) > _MAX_URL_LEN:
            return False
        
        # Get lowercase path for case-insensitive matching: O(p) where p = path length
        path_lower = parsed.path.lower()
        
        # === SPECIFIC SITE BLOCKLISTS ===
        # Block problematic paths discovered during crawling
        # Each check: O(p) for substring search
        
        # Genealogy pages cause 602 errors
        if '/genealogy/' in path_lower:
            return False
        
        # Javadoc infinite index
        if '/javadoc/index.html?' in path_lower:
            return False
        
        # People directory causes issues
        if '/people/' in path_lower:
            return False
        
        # PowerPoint slide exports (sld001.htm, sld002.htm, ...)
        if re.search(r'/sld\d+\.htm', path_lower):
            return False
        
        # === SUBDOMAIN RESTRICTIONS ===
        # Allow only main page for certain subdomains because of 602 errors
        
        if 'checkmate.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        
        if 'kgcs.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        
        if 'mt-live.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        
        if 'transformativeplay.ics.uci.edu' in host and path_lower not in ('', '/'):
            return False
        
        # Block deep publication pages due to 602 errors
        if 'graphics.ics.uci.edu' in host and '/publications/' in path_lower:
            return False
        
        # Block wiki pages due to 602 errors
        if 'grape.ics.uci.edu' in host and '/wiki/public/wiki/' in path_lower:
            return False
        
        # === QUERY-BASED TRAPS ===
        # Block news filter pages (infinite filter combinations)
        if '/happening/news/' in path_lower and ('filter[' in parsed.query.lower() or 'filter%5B' in parsed.query.lower()):
            return False
        
        # === PROBLEMATIC USER DIRECTORIES ===
        # Block specific professor course materials that cause errors
        
        if '/~goodrich/teach/' in path_lower and '/labmanual/' in path_lower:
            return False
        
        # Block entire fano subdomain (all pages return 601 errors)
        if 'fano.ics.uci.edu' in host:
            return False
        
        # Block specific sli.ics.uci.edu sections
        if 'sli.ics.uci.edu' in host and ('/extras/' in path_lower or '/classes/' in path_lower):
            return False
        
        # Block jutts course materials
        if '/~jutts/' in path_lower:
            return False
        
        # Block dechter courses
        if '/~dechter/courses/' in path_lower:
            return False
        
        # Block cypress subdirectory
        if '/~dsm/cypress/' in path_lower:
            return False
        
        # === CODE REPOSITORY BLOCKS ===
        # Block source code and build directories
        
        #Code somehow kept escaping to this/hardcode removal
        if "physics.uci.edu/~outreach/demos" in url.lower():
            return False
        
        # Block code repository directories (but allow docs)
        if any(x in path_lower for x in ['/src/', '/build/', '/lib/', '/bin/']):
            return False
        
        # Block software release directories
        if '/releases/' in path_lower and any(x in path_lower for x in ['/src/', '/build/', 'download']):
            return False
        
        # === DEEP COURSE MATERIAL BLOCKS ===
        # Only block deeply nested course paths (allow top-level)
        # Regex: O(p) for path length
        if re.match(r"^/~[^/]+/(ics|cs|inf)\d+/.+/.+/", path_lower):
            # This blocks: /~prof/ics32/lectures/week1/code/
            # But allows: /~prof/ics32/ and /~prof/ics32/syllabus
            return False
        
        # === FILE TYPE BLOCKS ===
        # Block makefiles and readme files: O(p)
        if path_lower.endswith(('makefile', 'readme', '/readme', '/makefile')):
            return False
        
        # === MEDIA GALLERY BLOCKS ===
        # Block image/photo galleries (not content pages): O(p)
        if any(x in path_lower for x in ['/pix/', '/images/', '/gallery/', '/photos/', 
                                          '/img/', '/pics/', '/picture/']):
            return False
        
        # Block specific video directory
        if path_lower.startswith("/~projects/cert/safire/meetings/"):
            return False
        
        # === CMS-SPECIFIC BLOCKS ===
        # Block attachment pages: O(p)
        if '/attachment/' in path_lower:
            return False
        
        # Block WordPress uploads directory
        if "/wp-content/uploads/" in path_lower:
            return False
        
        # Block seminar series with year ranges (causes loops)
        if "/seminar-series" in path_lower and re.search(r'\d{4}-\d{4}', path_lower):
            return False
        
        # Block nested seminar paths
        if path_lower.count("/seminar-series") > 1:
            return False
        
        # Block WordPress login/admin
        if path_lower.endswith("/wp-login.php") or "/wp-admin" in path_lower:
            return False
        
        # Block redirect loops
        if "redirect_to=" in parsed.query.lower():
            return False
        
        # === GENERIC ACTION URL DETECTION ===
        # Check if URL is an action rather than content: O(p) - see _looks_like_action_url
        if _looks_like_action_url(parsed):
            return False
        
        # === REGEX TRAP DETECTION ===
        # Check against compiled regex patterns
        # Each search: O(u) for URL length
        
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
        
        # === STRUCTURAL LOOP DETECTION ===
        # Detect repeating path segments: O(p)
        if _REPEAT_SEGMENTS_RE.search(path_lower + ("/" if not path_lower.endswith("/") else "")):
            return False
        
        # Detect date-based paths: O(p)
        if _DATE_PATH_RE.search(path_lower):
            return False
        
        # Detect pagination: O(p)
        if _PAGE_NUM_RE.search(path_lower):
            return False
        
        # === PATH DEPTH LIMIT ===
        # Prevent extremely deep nesting: O(p) - see _path_depth
        if _path_depth(parsed.path) > _MAX_PATH_DEPTH:
            return False
        
        # === QUERY STRING VALIDATION ===
        if parsed.query:
            # Length limit: O(1)
            if len(parsed.query) > _MAX_QUERY_LEN:
                return False
            
            # Parse parameters: O(q) where q = query length
            params = parse_qsl(parsed.query, keep_blank_values=True)
            
            # Parameter count limit: O(1)
            if len(params) > _MAX_QUERY_PARAMS:
                return False
            
            # Check each parameter: O(p) where p = param count
            for k, v in params:
                lk = k.lower()
                
                # Detect pagination/sorting traps with large numbers
                if lk in _TRAP_QUERY_KEYS and v.isdigit() and int(v) > 50:
                    return False
                
                if lk in _PAGER_KEYS and v.isdigit() and int(v) > 50:
                    return False
        
        # === HTML-LIKE PATH CHECK ===
        # Prefer HTML paths when no query string: O(1) - see _looks_htmlish
        if not parsed.query and not _looks_htmlish(parsed.path):
            return False
        
        # === FINAL EXTENSION CHECK ===
        # Block disallowed file extensions: O(p) regex match
        if _DISALLOWED_EXT_RE.match(parsed.path.lower()):
            return False
        
        # === ALL CHECKS PASSED ===
        return True
    
    except TypeError:
        # Log TypeError for debugging: O(1)
        print("TypeError for ", url)
        raise
    
    except Exception:
        # Catch all other exceptions and reject URL: O(1)
        return False



# Time Complexity: O(1)
# Space Complexity: O(1) - just returns reference
def get_analytics():
    """
    Expose the analytics object for final report generation.
    Called at the end of crawling to save final statistics.
    """
    return analytics
