import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")

ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,https://anubhav2402.github.io",
    ).split(",")
]

# Cache TTLs (seconds)
CACHE_TTL_QUOTES: int = 60
CACHE_TTL_NEWS: int = 300

# Twitter / X credentials (used by twikit)
TWITTER_USERNAME: str = os.getenv("TWITTER_USERNAME", "")
TWITTER_EMAIL: str = os.getenv("TWITTER_EMAIL", "")
TWITTER_PASSWORD: str = os.getenv("TWITTER_PASSWORD", "")

# Buzz engine settings
BUZZ_THRESHOLD: int = int(os.getenv("BUZZ_THRESHOLD", "1"))      # min unique accounts
BUZZ_WINDOW_HOURS: int = int(os.getenv("BUZZ_WINDOW_HOURS", "48"))
DISCOVERY_WINDOW_HOURS: int = int(os.getenv("DISCOVERY_WINDOW_HOURS", "48"))

# Scheduler intervals
SCRAPE_INTERVAL_MINUTES: int = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))
NEWS_INTERVAL_MINUTES: int = int(os.getenv("NEWS_INTERVAL_MINUTES", "15"))

# Paths
BASE_DIR = pathlib.Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TWITTER_COOKIES_FILE = BASE_DIR / "twitter_cookies.json"

# Cookies from env var (used on Render where filesystem is ephemeral)
# Set TWITTER_COOKIES_B64 = base64-encoded contents of twitter_cookies.json
TWITTER_COOKIES_B64: str = os.getenv("TWITTER_COOKIES_B64", "")

def write_cookies_from_env() -> bool:
    """Write twitter_cookies.json from env var if file doesn't exist. Returns True if written."""
    if TWITTER_COOKIES_FILE.exists() or not TWITTER_COOKIES_B64:
        return False
    try:
        import base64, json
        cookies = json.loads(base64.b64decode(TWITTER_COOKIES_B64).decode())
        TWITTER_COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not write cookies from env: %s", e)
        return False
