import redis
from redis.connection import ConnectionPool
from cachetools import TTLCache
import os
from typing import Optional, Any
import json
import logging

class RedisManager:
    _instance = None
    _pool = None
    _cache = TTLCache(maxsize=100, ttl=300)  # 5 dakikalık önbellek

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Redis bağlantı havuzunu başlat"""
        if self._pool is None:
            self._pool = ConnectionPool(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=int(os.getenv('REDIS_DB', 0)),
                password=os.getenv('REDIS_PASSWORD', None),
                decode_responses=True,
                max_connections=10
            )
        self._redis = redis.Redis(connection_pool=self._pool)

    def get(self, key: str, use_cache: bool = True) -> Optional[Any]:
        """Redis'ten veri getir, önbellekten kontrol et"""
        try:
            if use_cache and key in self._cache:
                return self._cache[key]

            value = self._redis.get(key)
            if value:
                try:
                    # JSON olarak parse etmeyi dene
                    parsed_value = json.loads(value)
                    if use_cache:
                        self._cache[key] = parsed_value
                    return parsed_value
                except json.JSONDecodeError:
                    # JSON değilse string olarak döndür
                    if use_cache:
                        self._cache[key] = value
                    return value
            return None
        except Exception as e:
            logging.error(f"Redis get error: {str(e)}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Redis'e veri kaydet"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if ttl:
                success = self._redis.setex(key, ttl, value)
            else:
                success = self._redis.set(key, value)
            
            if success and key in self._cache:
                self._cache[key] = value
            
            return bool(success)
        except Exception as e:
            logging.error(f"Redis set error: {str(e)}")
            return False

    def delete(self, key: str) -> bool:
        """Redis'ten veri sil"""
        try:
            success = self._redis.delete(key)
            if success and key in self._cache:
                del self._cache[key]
            return bool(success)
        except Exception as e:
            logging.error(f"Redis delete error: {str(e)}")
            return False

    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Redis sayaç arttır"""
        try:
            value = self._redis.incrby(key, amount)
            if key in self._cache:
                self._cache[key] = value
            return value
        except Exception as e:
            logging.error(f"Redis increment error: {str(e)}")
            return None

    def clear_cache(self):
        """Önbelleği temizle"""
        self._cache.clear()

    def scan_keys(self, pattern: str) -> list:
        """Belirli bir pattern'e uyan tüm anahtarları getir"""
        try:
            keys = []
            cursor = 0
            while True:
                cursor, partial_keys = self._redis.scan(cursor, match=pattern, count=100)
                keys.extend(partial_keys)
                if cursor == 0:
                    break
            return keys
        except Exception as e:
            logging.error(f"Redis scan error: {str(e)}")
            return []

    def cleanup_keys(self, pattern: str, max_keys: int = 1000):
        """Belirli bir pattern'e uyan eski anahtarları temizle"""
        try:
            keys = self.scan_keys(pattern)
            if len(keys) > max_keys:
                # En eski anahtarları sil
                keys_to_delete = keys[:-max_keys]
                for key in keys_to_delete:
                    self.delete(key)
        except Exception as e:
            logging.error(f"Redis cleanup error: {str(e)}")

    def close(self):
        """Redis bağlantısını kapat"""
        if self._pool:
            self._pool.disconnect() 