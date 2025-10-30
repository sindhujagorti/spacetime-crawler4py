from configparser import ConfigParser
from argparse import ArgumentParser

from utils.server_registration import get_cache_server
from utils.config import Config
from crawler import Crawler


def main(config_file, restart):
    cparser = ConfigParser()
    cparser.read(config_file)
    config = Config(cparser)
    config.cache_server = get_cache_server(config, restart)
    crawler = Crawler(config, restart)
    
    from scraper import get_analytics
    analytics = get_analytics()
    try:
        analytics.save_report(filename="report_progress_restart.txt")
        print("✅ Generated report_progress_restart.txt before crawl start")
    except Exception as e:
        print(f"⚠️ Could not generate initial report: {e}")
    
    # Load previous state if resuming
    if not restart:
        try:
            analytics.load_state()
        except:
            pass
    
    try:
        crawler.start()
    finally:
        # Save final report when crawler finishes or is interrupted
        print("\n" + "="*80)
        print("Crawler finished. Generating final report...")
        print("="*80)
        analytics.print_status()
        analytics.save_state()
        analytics.save_report(filename="FINAL_REPORT.txt")
        print("\nFinal report saved to FINAL_REPORT.txt")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--restart", action="store_true", default=False)
    parser.add_argument("--config_file", type=str, default="config.ini")
    args = parser.parse_args()
    main(args.config_file, args.restart)

