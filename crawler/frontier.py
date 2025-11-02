import os
import shelve
import time
from threading import RLock
from urllib.parse import urlparse
from collections import defaultdict

from utils import get_logger, get_urlhash, normalize
from scraper import is_valid

class Frontier(object):
    def __init__(self, config, restart):
        self.logger = get_logger("FRONTIER")
        self.config = config
        self.to_be_downloaded = list()
        
        self.lock = RLock()
        self.domain_lock = RLock()
        self.domain_last_accessed = defaultdict(float)
        
        if not os.path.exists(self.config.save_file) and not restart:
            self.logger.info(
                f"Did not find save file {self.config.save_file}, "
                f"starting from seed.")
        elif os.path.exists(self.config.save_file) and restart:
            self.logger.info(
                f"Found save file {self.config.save_file}, deleting it.")
            os.remove(self.config.save_file)
        
        self.save = shelve.open(self.config.save_file, writeback=True)
        
        if restart:
            for url in self.config.seed_urls:
                self.add_url(url)
        else:
            self._parse_save_file()
            if not self.save:
                for url in self.config.seed_urls:
                    self.add_url(url)

    def _parse_save_file(self):
        total_count = len(self.save)
        tbd_count = 0
        for url, completed in self.save.values():
            if not completed and is_valid(url):
                self.to_be_downloaded.append(url)
                tbd_count += 1
        self.logger.info(
            f"Found {tbd_count} urls to be downloaded from {total_count} "
            f"total urls discovered.")

    def _get_domain(self, url):
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except:
            return None

    def get_tbd_url(self):
        """ATOMIC: Check and mark domain in single lock acquisition"""
        with self.lock:
            if not self.to_be_downloaded:
                return None
            
            now = time.monotonic()
            
            for i in range(len(self.to_be_downloaded)):
                url = self.to_be_downloaded[i]
                domain = self._get_domain(url)
                
                if not domain:
                    continue
                
                # CRITICAL: Check AND mark in SAME lock
                with self.domain_lock:
                    last_access = self.domain_last_accessed.get(domain, 0.0)
                    time_since = now - last_access
                    
                    if time_since >= self.config.time_delay:
                        # Atomically: remove URL and mark domain
                        self.to_be_downloaded.pop(i)
                        self.domain_last_accessed[domain] = now
                        return url
            
            return None

    def add_url(self, url):
        url = normalize(url)
        urlhash = get_urlhash(url)
        
        with self.lock:
            try:
                if urlhash not in self.save:
                    self.save[urlhash] = (url, False)
                    self.to_be_downloaded.append(url)
            except Exception as e:
                self.logger.error(f"Error adding URL {url}: {e}")
    
    def mark_url_complete(self, url):
        urlhash = get_urlhash(url)
        
        with self.lock:
            try:
                self.save[urlhash] = (url, True)
            except Exception as e:
                self.logger.error(f"Error marking URL complete {url}: {e}")

    def next_ready_wait(self):
        with self.domain_lock:
            now = time.monotonic()
            waits = []
            for last in self.domain_last_accessed.values():
                remaining = self.config.time_delay - (now - last)
                if remaining > 0:
                    waits.append(remaining)
        return min(waits) if waits else 0.0