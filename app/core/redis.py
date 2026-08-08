from app.core.config import settings
import redis.asyncio as redis

redis_client = redis.from_url(settings.redis_url, decode_responses=True)
