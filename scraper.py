import re
from urllib.parse import urlparse, urljoin, urldefrag, parse_qsl
from bs4 import BeautifulSoup 

_ALLOWED_DOMAINS = ("ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu")
_REPEAT_SEGMENTS_RE = re.compile(r"/([^/]+/)\1{2,}")

_DATE_PATH_RE = re.compile(r"/(19|20)\d{2}/(0?[1-9]|1[0-2])(/(0?[1-9]|[12]\d|3[01]))?/")

_DISALLOWED_EXT_RE = re.compile(
    r".*\.(?:css|js|bmp|gif|jpe?g|ico|png|tiff?|mid|mp2|mp3|mp4|wav|avi|mov|mpeg|"
    r"ram|m4v|mkv|ogg|ogv|pdf|ps|eps|tex|pptx?|docx?|xlsx?|names|data|dat|exe|bz2|"
    r"tar|msi|bin|7z|psd|dmg|iso|epub|dll|cnf|tgz|sha1|thmx|mso|arff|rtf|jar|csv|"
    r"rm|smil|wmv|swf|wma|zip|rar|gz)$"
)

_LOW_VALUE_PATH_HINTS = (
    "/calendar", "/events", "/event", "/ical", "/wp-json", "/feed", "/tag/", "/author/",
    "/archive", "/archives", "/category/", "/comment", "/reply", "/login", "/signup"
)

_TRAP_QUERY_KEYS = ("sort", "order", "page", "offset", "limit", "start", "dir", "sessionid", "phpsessid")

_MAX_URL_LEN = 200            
_MAX_QUERY_LEN = 150          
_MAX_QUERY_PARAMS = 8    

def scraper(url, resp):
    links = extract_next_links(url, resp)
    return [link for link in links if is_valid(link)]

def extract_next_links(url, resp):
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
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

    if "html" not in ctype:
        return []

    content = getattr(raw, "content", b"")
    if not content:
        return []

    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception:
        return []

    base_url = getattr(raw, "url", None) or resp.url or url

    for tag in soup.find_all("a", href=True):
        href = tag.get("href")
        if not href:
            continue

        absolute_url = urljoin(base_url, href)
        absolute_url, _ = urldefrag(absolute_url)

        # quick early skip for obvious non-HTML files before is_valid
        if re.search(r'\.(pdf|jpg|jpeg|png|gif|mp4|zip|docx?|pptx?)$', absolute_url.lower()):
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
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        parsed = urlparse(url)
        if parsed.scheme not in set(["http", "https"]):
            return False
        
        host = parsed.netloc.lower()
        if not any(host.endswith(d) for d in _ALLOWED_DOMAINS):
            return False

        # length guards
        if len(url) > _MAX_URL_LEN:
            return False

        path_lower = parsed.path.lower()

        # avoid repeating segments (/a/b/a/b/), calendars (/2024/05/12/)
        if _REPEAT_SEGMENTS_RE.search(path_lower + ("/" if not path_lower.endswith("/") else "")):
            return False
        if _DATE_PATH_RE.search(path_lower):
            return False

        # low-value sections
        for hint in _LOW_VALUE_PATH_HINTS:
            if hint in path_lower:
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
                if lk in _TRAP_QUERY_KEYS:
                    if v.isdigit() and int(v) > 100:
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

    except Exception:
        return False
