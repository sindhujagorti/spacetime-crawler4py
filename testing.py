import types
import pytest
from scraper import is_valid, extract_next_links

# ---------- helpers (tiny mock of resp/raw_response) ----------
class MockRawResponse:
    def __init__(self, url=None, content=b"", headers=None):
        self.url = url
        self.content = content
        # mimic requests' CaseInsensitiveDict-ish .get()
        self.headers = headers or {}

class MockResp:
    def __init__(self, status=200, url=None, raw=None, error=None):
        self.status = status
        self.url = url
        self.raw_response = raw
        self.error = error

# ---------- is_valid() tests ----------
def test_is_valid_allows_allowed_domains_http_https():
    assert is_valid("http://ics.uci.edu/")
    assert is_valid("https://www.cs.uci.edu/")
    assert is_valid("https://informatics.uci.edu/people/")
    assert is_valid("https://stat.uci.edu/graduate/")

def test_is_valid_blocks_other_domains():
    assert not is_valid("https://uci.edu/")               # parent domain only
    assert not is_valid("https://example.com/")
    assert not is_valid("ftp://ics.uci.edu/")             # bad scheme

def test_is_valid_blocks_disallowed_extensions():
    assert not is_valid("https://ics.uci.edu/file.pdf")
    assert not is_valid("https://cs.uci.edu/img/photo.jpg")
    assert not is_valid("https://informatics.uci.edu/archive.zip")

def test_is_valid_blocks_date_calendar_paths():
    assert not is_valid("https://ics.uci.edu/2024/05/12/")
    assert not is_valid("https://cs.uci.edu/news/2023/7/1/")

def test_is_valid_blocks_repeating_segments():
    # e.g., /a/b/a/b/a/
    assert not is_valid("https://ics.uci.edu/a/b/a/b/a/")
    # benign non-repeating should pass
    assert is_valid("https://ics.uci.edu/a/b/c/")

def test_is_valid_blocks_low_value_paths():
    assert not is_valid("https://ics.uci.edu/calendar/")
    assert not is_valid("https://cs.uci.edu/category/events/")
    assert not is_valid("https://informatics.uci.edu/wp-json/")

def test_is_valid_query_traps():
    # too many params
    many = "&".join(f"k{i}=v" for i in range(20))
    assert not is_valid(f"https://ics.uci.edu/?{many}")
    # page very large
    assert not is_valid("https://ics.uci.edu/?page=101")
    # reasonable page should pass
    assert is_valid("https://ics.uci.edu/?page=2")

def test_is_valid_too_long_url():
    long_tail = "a" * 210
    assert not is_valid(f"https://ics.uci.edu/{long_tail}")

# ---------- extract_next_links() tests ----------
def test_extract_returns_empty_on_non_200():
    resp = MockResp(status=404)
    assert extract_next_links("https://ics.uci.edu/", resp) == []

def test_extract_handles_missing_headers_gracefully():
    raw = MockRawResponse(url="https://ics.uci.edu/", content=b"<html></html>", headers=None)
    resp = MockResp(status=200, url="https://ics.uci.edu/", raw=raw)
    # No headers -> treated as non-HTML by your code; returns []
    assert extract_next_links("https://ics.uci.edu/", resp) == []

def test_extract_non_html_content_type_returns_empty():
    raw = MockRawResponse(
        url="https://ics.uci.edu/",
        content=b"<html><a href='/x'>x</a></html>",
        headers={"Content-Type": "application/json"}
    )
    resp = MockResp(status=200, url="https://ics.uci.edu/", raw=raw)
    assert extract_next_links("https://ics.uci.edu/", resp) == []

def test_extract_html_content_type_variants():
    raw = MockRawResponse(
        url="https://ics.uci.edu/",
        content=b"<html><a href='/a'>A</a><a href='#frag'>F</a></html>",
        headers={"Content-Type": "text/html; charset=UTF-8"}
    )
    resp = MockResp(status=200, url="https://ics.uci.edu/", raw=raw)
    out = extract_next_links("https://ics.uci.edu/", resp)
    # should absolutize and defragment
    assert "https://ics.uci.edu/a" in out
    assert all("#" not in u for u in out)

def test_extract_skips_obvious_binaries_early():
    raw = MockRawResponse(
        url="https://ics.uci.edu/",
        content=b"<html><a href='/report.pdf'>PDF</a><a href='/news/'>News</a></html>",
        headers={"Content-Type": "text/html"}
    )
    resp = MockResp(status=200, url="https://ics.uci.edu/", raw=raw)
    out = extract_next_links("https://ics.uci.edu/", resp)
    assert "https://ics.uci.edu/report.pdf" not in out
    assert "https://ics.uci.edu/news/" in out

def test_extract_absolutizes_and_dedupes():
    raw = MockRawResponse(
        url="https://ics.uci.edu/dir/page.html",
        content=b"<html>"
                b"<a href='sub'>s1</a>"
                b"<a href='sub#fragment'>s2</a>"
                b"<a href='https://ics.uci.edu/sub'>s3</a>"
                b"</html>",
        headers={"Content-Type": "text/html"}
    )
    resp = MockResp(status=200, url="https://ics.uci.edu/dir/page.html", raw=raw)
    out = extract_next_links("https://ics.uci.edu/dir/page.html", resp)
    # all should normalize to the same absolute URL once defragmented, and be unique
    assert out == ["https://ics.uci.edu/dir/sub", "https://ics.uci.edu/sub"] or \
           out == ["https://ics.uci.edu/sub", "https://ics.uci.edu/dir/sub"]