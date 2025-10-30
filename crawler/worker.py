from threading import Thread
from inspect import getsource
from utils.download import download
from utils import get_logger
import scraper
import time


class Worker(Thread):
    def __init__(self, worker_id, config, frontier):
        self.logger = get_logger(f"Worker-{worker_id}", "Worker")
        self.config = config
        self.frontier = frontier
        self.worker_id = worker_id
        
        # basic check for requests in scraper
        assert {getsource(scraper).find(req) for req in {"from requests import", "import requests"}} == {-1}, "Do not use requests in scraper.py"
        assert {getsource(scraper).find(req) for req in {"from urllib.request import", "import urllib.request"}} == {-1}, "Do not use urllib.request in scraper.py"
        
        super().__init__(daemon=True)
        
    def run(self):
        # Track consecutive failures to get URLs (for backoff)
        empty_attempts = 0
        max_empty_attempts = 10
        
        while True:
            tbd_url = self.frontier.get_tbd_url()
            
            if not tbd_url:
                empty_attempts += 1
                
                # Check if frontier is truly empty or just waiting for politeness
                if empty_attempts >= max_empty_attempts:
                    self.logger.info("Frontier is empty. Stopping Crawler.")
                    break
                
                # Sleep briefly and try again (might be waiting for domain politeness)
                time.sleep(0.1)
                continue
            
            # Reset empty attempts counter - we got a URL
            empty_attempts = 0
            
            # Download the URL
            resp = download(tbd_url, self.config, self.logger)
            self.logger.info(
                f"Downloaded {tbd_url}, status <{resp.status}>, "
                f"using cache {self.config.cache_server}.")
            
            # Scrape URLs from the response
            scraped_urls = scraper.scraper(tbd_url, resp)
            
            # Add scraped URLs to frontier
            for scraped_url in scraped_urls:
                self.frontier.add_url(scraped_url)
            
            # Mark this URL as complete
            self.frontier.mark_url_complete(tbd_url)
            
            # Note: We don't sleep here because the frontier already
            # enforces per-domain politeness in get_tbd_url()