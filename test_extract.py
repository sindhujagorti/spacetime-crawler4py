from types import SimpleNamespace
from scraper import extract_next_links

class DummyRaw:
    def __init__(self):
        self.url = "https://example.com/page.html"
        self.headers = {"Content-Type": "text/html"}
        self.content = b"""
        <html>
        <body>
            <a href="https://ics.uci.edu">UCI</a>
            <a href="/about">About</a>
            <a href="mailto:test@example.com">Email</a>
        </body>
        </html>
        """

# Mock response object like the crawler gives you
resp = SimpleNamespace(status=200, raw_response=DummyRaw())

# Run your extraction function
links = extract_next_links("https://example.com", resp)
print("Extracted links:", links)
