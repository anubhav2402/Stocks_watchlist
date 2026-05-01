from cachetools import TTLCache
from config import CACHE_TTL_QUOTES, CACHE_TTL_NEWS

quote_cache: TTLCache = TTLCache(maxsize=500, ttl=CACHE_TTL_QUOTES)
news_cache: TTLCache = TTLCache(maxsize=50, ttl=CACHE_TTL_NEWS)
catalyst_cache: TTLCache = TTLCache(maxsize=500, ttl=6 * 3600)  # 6-hour TTL
