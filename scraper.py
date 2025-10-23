import re
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup 

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
    if raw is None or not getattr(raw, "content", None):
        return []

    ctype = ""
    try:
        ctype = raw.headers.get("Content-Type", "") or ""
    except Exception:
        ctype = ""

    if "html" not in ctype.lower():
        return []  

    try:
        soup = BeautifulSoup(resp.raw_response.content, 'html.parser')
    except Exception:
        return links

    base_url = getattr(resp.raw_response, "url", None) or resp.url or url

    for tag in soup.find_all('a', href=True):
        href = tag.get('href')
        if not href:
            continue

        absolute_url = urljoin(base_url, href)
        absolute_url, _ = urldefrag(absolute_url)

        if re.search(r'\.(pdf|jpg|jpeg|png|gif|mp4|zip|docx?|pptx?)$', absolute_url.lower()):
            continue

        domain = urlparse(absolute_url).netloc.lower()
        if any(domain.endswith(d) for d in [
            "ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu"
        ]):
            links.append(absolute_url)

    seen = set()
    unique_links = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique_links.append(l)

    return unique_links

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
