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
        
        # Thread-safety locks
        self.lock = RLock()  # Main lock for frontier operations
        self.domain_lock = RLock()  # Lock for domain timing access
        
        # Per-domain politeness tracking
        # Maps domain -> last download timestamp
        self.domain_last_accessed = defaultdict(float)
        
        if not os.path.exists(self.config.save_file) and not restart:
            # Save file does not exist, but request to load save.
            self.logger.info(
                f"Did not find save file {self.config.save_file}, "
                f"starting from seed.")
        elif os.path.exists(self.config.save_file) and restart:
            # Save file does exists, but request to start from seed.
            self.logger.info(
                f"Found save file {self.config.save_file}, deleting it.")
            os.remove(self.config.save_file)
        
        # Load existing save file, or create one if it does not exist.
        self.save = shelve.open(self.config.save_file)
        
        if restart:
            for url in self.config.seed_urls:
                self.add_url(url)
        else:
            # Set the frontier state with contents of save file.
            self._parse_save_file()
            if not self.save:
                for url in self.config.seed_urls:
                    self.add_url(url)

    def _parse_save_file(self):
        '''This function can be overridden for alternate saving techniques.'''
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
        """Extract domain from URL for politeness tracking."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except:
            return None

    def _can_fetch_domain(self, domain):
        """Check if enough time has passed since last fetch from this domain."""
        if not domain:
            return True
        
        with self.domain_lock:
            last_access = self.domain_last_accessed.get(domain, 0)
            current_time = time.time()
            time_since_last = current_time - last_access
            
            # Check if 500ms (0.5s) has passed
            if time_since_last >= self.config.time_delay:
                return True
            return False

    def _mark_domain_accessed(self, domain):
        """Mark that we've accessed this domain right now."""
        if not domain:
            return
        
        with self.domain_lock:
            self.domain_last_accessed[domain] = time.time()

    def get_tbd_url(self):
        """
        Get a URL to download, respecting per-domain politeness.
        Returns None if no URL is available or all domains need to wait.
        """
        with self.lock:
            if not self.to_be_downloaded:
                return None
            
            # Try to find a URL whose domain is ready
            for i in range(len(self.to_be_downloaded)):
                url = self.to_be_downloaded[i]
                domain = self._get_domain(url)
                
                if self._can_fetch_domain(domain):
                    # Remove this URL from the list
                    self.to_be_downloaded.pop(i)
                    # Mark domain as accessed
                    self._mark_domain_accessed(domain)
                    return url
            
            # No URL available that respects politeness
            # Return None and let worker sleep briefly
            return None

    def add_url(self, url):
        """Thread-safe URL addition."""
        url = normalize(url)
        urlhash = get_urlhash(url)
        
        with self.lock:
            if urlhash not in self.save:
                self.save[urlhash] = (url, False)
                self.save.sync()
                self.to_be_downloaded.append(url)
    
    def mark_url_complete(self, url):
        """Thread-safe URL completion marking."""
        urlhash = get_urlhash(url)
        
        with self.lock:
            if urlhash not in self.save:
                # This should not happen.
                self.logger.error(
                    f"Completed url {url}, but have not seen it before.")
            
            self.save[urlhash] = (url, True)
            self.save.sync()