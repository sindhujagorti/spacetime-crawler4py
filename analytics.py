import json
import re
from collections import defaultdict, Counter
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import os, time

class CrawlerAnalytics:
    def __init__(self, stop_words_file="stop_words.txt"):
        """Initialize analytics tracking"""
        self.unique_urls = set() 
        self.longest_page = {"url": "", "word_count": 0}
        self.word_frequencies = Counter()  
        self.subdomain_pages = defaultdict(set)  
        
        self.stop_words = self._load_stop_words(stop_words_file)

        self.state_path = os.environ.get("ANALYTICS_STATE_PATH") or \
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "analytics_state.json")
        self.report_dir = os.getcwd() 
    
    def _load_stop_words(self, filename):
        """Load stop words from file"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return set(word.strip().lower() for word in f)
        except FileNotFoundError:
            print(f"Warning: {filename} not found. Using default stop words.")
            return {
                'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
                'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
                'to', 'was', 'will', 'with', 'this', 'but', 'they', 'have', 'had',
                'what', 'when', 'where', 'who', 'which', 'why', 'how'
            }
    
    def extract_words(self, soup):
        """Extract and clean words from BeautifulSoup object"""
        for script in soup(["script", "style", "meta", "noscript"]):
            script.decompose()
        
        text = soup.get_text(separator=' ', strip=True)
        
        words = re.findall(r'\b[a-z0-9]+\b', text.lower())
        
        return words
    
    def process_page(self, url, content):
        self.unique_urls.add(url)
        
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()
        
        if hostname.endswith('.uci.edu'):
            self.subdomain_pages[hostname].add(url)
        
        try:
            if isinstance(content, bytes):
                soup = BeautifulSoup(content, 'html.parser')
            else:
                soup = BeautifulSoup(content, 'html.parser')
        except Exception as e:
            print(f"Error parsing {url}: {e}")
            return
        
        words = self.extract_words(soup)
        
        filtered_words = [w for w in words if w not in self.stop_words and len(w) > 1]
        
        self.word_frequencies.update(filtered_words)
        
        word_count = len(filtered_words)
        if word_count > self.longest_page["word_count"]:
            self.longest_page = {
                "url": url,
                "word_count": word_count
            }
    
    def get_unique_page_count(self):
        """Return count of unique pages"""
        return len(self.unique_urls)
    
    def get_longest_page(self):
        """Return the longest page info"""
        return self.longest_page
    
    def get_top_words(self, n=50):
        """Return top N most common words"""
        return self.word_frequencies.most_common(n)
    
    def get_subdomains(self):
        """
        Return sorted list of subdomains with their unique page counts
        Returns list of tuples: [(subdomain, count), ...]
        """
        subdomain_counts = [
            (subdomain, len(urls)) 
            for subdomain, urls in self.subdomain_pages.items()
        ]
        subdomain_counts.sort(key=lambda x: x[0])
        return subdomain_counts
    
    def save_report(self, filename="report.txt"):
        """Save analytics report to file"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("WEB CRAWLER ANALYTICS REPORT\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"1. Number of unique pages: {self.get_unique_page_count()}\n\n")
            
            longest = self.get_longest_page()
            f.write(f"2. Longest page (by word count):\n")
            f.write(f"   URL: {longest['url']}\n")
            f.write(f"   Word count: {longest['word_count']}\n\n")
            
            f.write("3. Top 50 most common words:\n")
            top_words = self.get_top_words(50)
            for i, (word, count) in enumerate(top_words, 1):
                f.write(f"   {i}. {word}: {count}\n")
            f.write("\n")
            
            f.write("4. Subdomains in uci.edu domain:\n")
            subdomains = self.get_subdomains()
            f.write(f"   Total subdomains found: {len(subdomains)}\n\n")
            for subdomain, count in subdomains:
                f.write(f"   {subdomain}, {count}\n")
        
        print(f"\nReport saved to {filename}")
    
    def save_state(self, filename="analytics_state.json"):
        """Save analytics state to JSON (for crash recovery)"""
        state = {
            "unique_urls": list(self.unique_urls),
            "longest_page": self.longest_page,
            "word_frequencies": dict(self.word_frequencies),
            "subdomain_pages": {k: list(v) for k, v in self.subdomain_pages.items()}
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    
    def load_state(self, filename="analytics_state.json"):
        """Load analytics state from JSON (for crash recovery)"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            self.unique_urls = set(state["unique_urls"])
            self.longest_page = state["longest_page"]
            self.word_frequencies = Counter(state["word_frequencies"])
            self.subdomain_pages = defaultdict(set, {
                k: set(v) for k, v in state["subdomain_pages"].items()
            })
            print(f"Loaded analytics state from {filename}")
        except FileNotFoundError:
            print(f"No saved state found at {filename}. Starting fresh.")
    
    def print_status(self):
        """Print current crawling status"""
        print(f"\n--- Crawler Status ---")
        print(f"Unique pages crawled: {self.get_unique_page_count()}")
        print(f"Unique words found: {len(self.word_frequencies)}")
        print(f"Subdomains discovered: {len(self.subdomain_pages)}")
        print(f"Longest page so far: {self.longest_page['word_count']} words")
        print(f"----------------------\n")