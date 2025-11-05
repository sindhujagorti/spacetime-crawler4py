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
        #worker_id on the instance (useful for per-thread logs/metrics).
        self.worker_id = worker_id

        # basic check for requests in scraper
        assert {getsource(scraper).find(req) for req in {"from requests import", "import requests"}} == {-1}, "Do not use requests in scraper.py"
        assert {getsource(scraper).find(req) for req in {"from urllib.request import", "import urllib.request"}} == {-1}, "Do not use urllib.request in scraper.py"

        super().__init__(daemon=True)

    def run(self):
        while True:
            tbd_url = self.frontier.get_tbd_url()
            # hanged: don't exit when no URL is immediately available.
            # back off based on next_ready_wait() (domain politeness) with a bounded sleep.
            if not tbd_url:
                wait = self.frontier.next_ready_wait()
                time.sleep(min(max(wait, 0.05), 1.0))
                continue

            # Download
            resp = download(tbd_url, self.config, self.logger)
            
            self.logger.info(
                f"Downloaded {tbd_url}, status <{resp.status}>, "
                f"using cache {self.config.cache_server}."
            )

            # Scrape & enqueue
            scraped_urls = scraper.scraper(tbd_url, resp)
            for scraped_url in scraped_urls:
                self.frontier.add_url(scraped_url)

            # Mark complete
            self.frontier.mark_url_complete(tbd_url)

# Removed: time.sleep(self.config.time_delay)
# Frontier now enforces per-domain politeness; workers don't add a global delay.
