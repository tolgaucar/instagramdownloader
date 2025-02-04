from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import instaloader
import os
from dotenv import load_dotenv
import uuid
from datetime import datetime, timedelta
import time
import re
from typing import Optional, Dict
import json
from collections import defaultdict
import asyncio
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import logging
import logging.handlers
import traceback
import sys
import redis
import random
from pathlib import Path
import aiohttp
import io
import requests

# Logging konfigürasyonu
def setup_logging():
    # Log klasörü oluştur
    os.makedirs('logs', exist_ok=True)
    
    # Ana logger'ı yapılandır
    logger = logging.getLogger('instatest')
    logger.setLevel(logging.DEBUG)
    
    # Formatlayıcı - varsayılan değerler ekle
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s '
        '[ip:%(client_ip)-15s] [endpoint:%(endpoint)-20s] '
        '[response_time:%(response_time).2fms] '
        '[status_code:%(status_code)s]',
        defaults={
            'client_ip': '-',
            'endpoint': '-',
            'response_time': 0.0,
            'status_code': 0
        }
    )
    
    # Dosya handler'ları
    # Genel loglar
    general_handler = logging.handlers.TimedRotatingFileHandler(
        'logs/instatest.log',
        when='midnight',
        interval=1,
        backupCount=30  # 30 günlük log tut
    )
    general_handler.setFormatter(formatter)
    general_handler.setLevel(logging.INFO)
    
    # Hata logları
    error_handler = logging.handlers.RotatingFileHandler(
        'logs/error.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    
    # Debug logları
    debug_handler = logging.handlers.RotatingFileHandler(
        'logs/debug.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=3
    )
    debug_handler.setFormatter(formatter)
    debug_handler.setLevel(logging.DEBUG)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # Handler'ları logger'a ekle
    logger.addHandler(general_handler)
    logger.addHandler(error_handler)
    logger.addHandler(debug_handler)
    logger.addHandler(console_handler)
    
    return logger

# Logger'ı oluştur
logger = setup_logging()

# Request modeli
class DownloadRequest(BaseModel):
    url: str
    type: Optional[str] = "post"  # post, reel, story, igtv

# Instaloader instance pool
class InstaloaderPool:
    def __init__(self, pool_size: int = 5):
        self.pool = []
        self.pool_size = pool_size
        self.current = 0
        self.lock = asyncio.Lock()
        
        for _ in range(pool_size):
            loader = instaloader.Instaloader(
                download_video_thumbnails=False,
                save_metadata=False,
                download_geotags=False,
                download_comments=False,
                post_metadata_txt_pattern="",
                max_connection_attempts=3,
                filename_pattern="{shortcode}",
                quiet=True,
                sleep=True  # Rate limiting'i aç
            )
            self.pool.append(loader)
            
    def load_cookies_to_loader(self, loader, cookies):
        """Cookie'leri Instaloader instance'ına yükle"""
        # Mevcut cookie'leri temizle
        loader.context._session.cookies.clear()
        
        # Yeni cookie'leri ekle
        for key, value in cookies.items():
            loader.context._session.cookies.set(
                key,
                value,
                domain='.instagram.com',
                path='/'
            )
        
        # Kullanıcı ID'sini ayarla
        if 'ds_user_id' in cookies:
            loader.context.user_id = cookies['ds_user_id']
            
    async def get_loader(self):
        async with self.lock:
            loader = self.pool[self.current]
            self.current = (self.current + 1) % self.pool_size
            return loader

class CookieManager:
    def __init__(self):
        self.cookies = []
        self.current_index = 0
        self.cookie_health = {}  # Cookie sağlık durumları
        self.cookie_cooldowns = {}  # Cookie'lerin dinlenme süreleri
        self.request_counts = {}  # Her cookie için istek sayısı
        self.max_requests_per_hour = 100  # Her cookie için saatlik maksimum istek
        self.load_cookies()

    def load_cookies(self):
        cookie_dir = Path("cookies")
        if not cookie_dir.exists():
            raise Exception("Cookies directory not found")

        # Tüm cookie'leri yükle
        for cookie_file in cookie_dir.glob("*.json"):
            with open(cookie_file) as f:
                try:
                    cookie_data = json.load(f)
                    cookie_id = cookie_file.stem  # account1, account2, vs.
                    self.cookies.append({
                        'id': cookie_id,
                        'data': cookie_data,
                        'file': cookie_file
                    })
                    # Cookie sağlık durumunu başlat
                    self.cookie_health[cookie_id] = {
                        'challenges': 0,  # Challenge sayısı
                        'successes': 0,   # Başarılı istek sayısı
                        'last_success': None,  # Son başarılı istek zamanı
                        'last_challenge': None,  # Son challenge zamanı
                        'last_used': None  # Son kullanım zamanı
                    }
                    # İstek sayacını başlat
                    self.request_counts[cookie_id] = []
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse cookie file: {cookie_file}")

        if not self.cookies:
            raise Exception("No valid cookies found")

    def get_next_cookie(self):
        """En uygun cookie'yi seç"""
        now = datetime.now()
        available_cookies = []

        # Eski istek sayılarını temizle (1 saatten eski)
        for cookie_id in self.request_counts:
            self.request_counts[cookie_id] = [
                timestamp for timestamp in self.request_counts[cookie_id]
                if (now - timestamp).total_seconds() < 3600
            ]

        for cookie in self.cookies:
            cookie_id = cookie['id']
            health = self.cookie_health[cookie_id]
            cooldown = self.cookie_cooldowns.get(cookie_id)
            request_count = len(self.request_counts[cookie_id])

            # Cookie kullanılabilir mi kontrol et
            if cooldown and now < cooldown:
                continue

            if request_count >= self.max_requests_per_hour:
                continue

            # Cookie'nin sağlık puanını hesapla
            health_score = health['successes'] - (health['challenges'] * 2)
            
            # Son kullanımdan beri geçen süreye göre bonus puan
            if health['last_used']:
                minutes_since_last_use = (now - health['last_used']).total_seconds() / 60
                if minutes_since_last_use > 5:  # 5 dakikadan fazla dinlenmişse bonus
                    health_score += min(minutes_since_last_use / 5, 10)  # Maximum 10 bonus

            # Rate limit durumuna göre puan
            rate_limit_score = (self.max_requests_per_hour - request_count) / self.max_requests_per_hour * 10
            health_score += rate_limit_score

            available_cookies.append((cookie, health_score))

        if not available_cookies:
            return None

        # En yüksek puanlı cookie'yi seç
        best_cookie = max(available_cookies, key=lambda x: x[1])[0]
        cookie_id = best_cookie['id']

        # Cookie kullanım bilgilerini güncelle
        self.cookie_health[cookie_id]['last_used'] = now
        self.request_counts[cookie_id].append(now)

        return best_cookie['data']

    def mark_cookie_success(self, cookie_data):
        """Cookie başarılı olduğunda çağrılır"""
        for cookie in self.cookies:
            if cookie['data'] == cookie_data:
                cookie_id = cookie['id']
                self.cookie_health[cookie_id]['successes'] += 1
                self.cookie_health[cookie_id]['last_success'] = datetime.now()
                # Dinlenme süresini kaldır
                self.cookie_cooldowns.pop(cookie_id, None)
                break

    def mark_cookie_challenge(self, cookie_data):
        """Cookie challenge aldığında çağrılır"""
        now = datetime.now()
        for cookie in self.cookies:
            if cookie['data'] == cookie_data:
                cookie_id = cookie['id']
                health = self.cookie_health[cookie_id]
                health['challenges'] += 1
                health['last_challenge'] = now
                
                # Challenge sayısına göre dinlenme süresi belirle
                cooldown_minutes = min(30 * (2 ** (health['challenges'] - 1)), 720)  # Max 12 saat
                self.cookie_cooldowns[cookie_id] = now + timedelta(minutes=cooldown_minutes)
                
                logger.info(f"Cookie {cookie_id} will cool down for {cooldown_minutes} minutes")
                break

    def mark_cookie_rate_limited(self, cookie_data):
        """Cookie rate limit aldığında çağrılır"""
        now = datetime.now()
        for cookie in self.cookies:
            if cookie['data'] == cookie_data:
                cookie_id = cookie['id']
                # 30 dakika dinlenmeye al
                self.cookie_cooldowns[cookie_id] = now + timedelta(minutes=30)
                logger.info(f"Cookie {cookie_id} rate limited, cooling down for 30 minutes")
                break

# Redis bağlantısı
redis_client = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    decode_responses=True
)

# Rate limiting için Redis kullanan sınıf
class RedisRateLimiter:
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        self.redis = redis_client
        self.max_requests = max_requests
        self.time_window = time_window
        
    def is_allowed(self, client_id: str) -> bool:
        current = int(time.time())
        key = f"rate_limit:{client_id}"
        
        pipe = self.redis.pipeline()
        
        # Eski kayıtları temizle ve yeni istek ekle
        pipe.zremrangebyscore(key, 0, current - self.time_window)
        pipe.zadd(key, {str(current): current})
        pipe.zcard(key)
        pipe.expire(key, self.time_window)
        
        _, _, request_count, _ = pipe.execute()
        
        return request_count <= self.max_requests

# Task yönetimi için
class TaskManager:
    def __init__(self, max_age_minutes: int = 30):
        self.tasks: Dict[str, dict] = {}
        self.max_age = timedelta(minutes=max_age_minutes)
        
    def add_task(self, task_id: str, status: str = "processing"):
        self.tasks[task_id] = {
            "status": status,
            "result": None,
            "created_at": datetime.now()
        }
        
    def update_task(self, task_id: str, status: str, result: dict = None):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["result"] = result
            
    def get_task(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)
        
    def cleanup_old_tasks(self):
        now = datetime.now()
        old_tasks = [task_id for task_id, task in self.tasks.items()
                    if now - task["created_at"] > self.max_age]
        for task_id in old_tasks:
            del self.tasks[task_id]

# Global instances
load_dotenv()
rate_limiter = RedisRateLimiter(max_requests=100, time_window=60)
task_manager = TaskManager()
cookie_manager = CookieManager()

# Instaloader pool'unu oluştur ve cookie'leri yükle
loader_pool = InstaloaderPool()

# İlk cookie'yi yükle
try:
    initial_cookies = cookie_manager.get_next_cookie()
    for loader in loader_pool.pool:
        loader_pool.load_cookies_to_loader(loader, initial_cookies)
    logger.info("Initial cookies loaded successfully")
except Exception as e:
    logger.error(f"Initial cookie loading failed: {str(e)}")

# Periyodik temizlik işlemi
async def periodic_cleanup():
    while True:
        task_manager.cleanup_old_tasks()
        await asyncio.sleep(300)  # 5 dakikada bir

app = FastAPI(title="InstaTest - Instagram Media Downloader")

# Middleware'ler
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Middleware for request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Request başlangıç zamanı
    start_time = datetime.now()
    
    # Extra log bilgileri
    extra = {
        'client_ip': request.client.host,
        'endpoint': request.url.path,
        'response_time': 0,
        'status_code': 0
    }
    
    try:
        # Request detaylarını logla
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra=extra
        )
        
        # Request'i işle
        response = await call_next(request)
        
        # Response süresini hesapla
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        extra['response_time'] = response_time
        extra['status_code'] = response.status_code
        
        # Başarılı response'u logla
        logger.info(
            f"Request completed: {request.method} {request.url.path}",
            extra=extra
        )
        
        return response
        
    except Exception as e:
        # Hata süresini hesapla
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        extra['response_time'] = response_time
        extra['status_code'] = 500
        
        # Hatayı detaylı şekilde logla
        logger.error(
            f"Request failed: {request.method} {request.url.path}\n"
            f"Error: {str(e)}\n"
            f"Traceback: {traceback.format_exc()}",
            extra=extra
        )
        raise

@app.on_event("startup")
async def startup_event():
    logger.info("Application starting up", extra={
        'client_ip': '-',
        'endpoint': 'startup',
        'response_time': 0.0,
        'status_code': 0
    })
    asyncio.create_task(periodic_cleanup())

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutting down", extra={
        'client_ip': '-',
        'endpoint': 'shutdown',
        'response_time': 0.0,
        'status_code': 0
    })

# Instagram kimlik bilgileri
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')

# Global Instaloader instance
L = instaloader.Instaloader(
    download_video_thumbnails=False,
    save_metadata=False,
    download_geotags=False,
    download_comments=False,
    post_metadata_txt_pattern="",
    max_connection_attempts=3,
    filename_pattern="{shortcode}",
    quiet=True,
    sleep=False,  # Rate limiting'i kapat
    download_pictures=True,
    download_videos=True,
    compress_json=False
)

async def retry_with_backoff(func, max_retries=5, initial_delay=10):
    """Exponential backoff ile retry mekanizması"""
    for attempt in range(max_retries):
        try:
            return await func()
        except instaloader.exceptions.InstaloaderException as e:
            if attempt == max_retries - 1:
                raise
                
            # Hata mesajını kontrol et
            error_msg = str(e).lower()
            if any(msg in error_msg for msg in ["unauthorized", "please wait", "failed", "not found"]):
                # Yeni cookie dene
                try:
                    new_cookies = cookie_manager.get_next_cookie()
                    loader = await loader_pool.get_loader()
                    loader_pool.load_cookies_to_loader(loader, new_cookies)
                    logger.info(f"Yeni cookie yüklendi: {loader.context.user_id}")
                except Exception as cookie_error:
                    logger.error(f"Cookie değiştirme hatası: {str(cookie_error)}")
            
            # Exponential backoff ile bekle
            delay = initial_delay * (2 ** attempt) + random.uniform(1, 5)
            logger.warning(f"Retry attempt {attempt + 1}/{max_retries}, waiting {delay:.2f} seconds...")
            await asyncio.sleep(delay)

async def download_media_from_instagram(url: str, client_id: str) -> dict:
    """Instagram'dan medya URL'lerini al"""
    extra = {
        'client_ip': client_id,
        'endpoint': '/api/download',
        'response_time': 0,
        'status_code': 200
    }
    
    start_time = datetime.now()
    
    try:
        # Rate limit kontrolü
        if not rate_limiter.is_allowed(client_id):
            logger.warning(f"Rate limit exceeded for client: {client_id}", extra=extra)
            return {"success": False, "error": "Rate limit aşıldı. Lütfen biraz bekleyin."}
        
        shortcode = get_shortcode_from_url(url)
        if not shortcode:
            logger.warning(f"Invalid Instagram URL: {url}", extra=extra)
            return {"success": False, "error": "Geçerli bir Instagram URL'si değil"}
        
        # Retry mekanizması ile download işlemini gerçekleştir
        async def download_attempt():
            loader = await loader_pool.get_loader()
            
            try:
                # Story URL'si kontrolü
                if shortcode.startswith('story_'):
                    parts = shortcode.split('_', 2)  # En fazla 2 kere böl
                    if len(parts) != 3:
                        raise instaloader.exceptions.InstaloaderException("Invalid story URL format")
                    
                    username = parts[1]
                    story_id = parts[2]
                    logger.debug(f"Attempting to fetch story - username: {username}, id: {story_id}")
                    
                    try:
                        # Profil aramayı yeni API ile yap
                        profile_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)',
                            'X-IG-App-ID': '936619743392459',  # Instagram web app ID
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                        
                        async with aiohttp.ClientSession() as session:
                            async with session.get(profile_url, headers=headers, cookies=loader.context._session.cookies) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    if 'data' in data and 'user' in data['data']:
                                        user_id = data['data']['user']['id']
                                        logger.debug(f"Found user ID: {user_id} for username: {username}")
                                        
                                        # Story'leri al
                                        stories = loader.get_stories([user_id])
                                        for story in stories:
                                            for item in story.get_items():
                                                logger.debug(f"Checking story item: {item.mediaid}")
                                                if str(item.mediaid) == story_id:
                                                    if item.is_video:
                                                        return item.video_url, 'mp4'
                                                    return item.url, 'jpg'
                                    
                        raise instaloader.exceptions.InstaloaderException(f"Could not fetch stories for {username}")
                            
                    except Exception as e:
                        logger.error(f"Story fetch error: {str(e)}")
                        raise instaloader.exceptions.InstaloaderException(f"Failed to fetch stories: {str(e)}")
                
                # Normal post işlemi
                post = instaloader.Post.from_shortcode(loader.context, shortcode)
                
                # Post erişilebilir mi kontrol et
                if not post or not hasattr(post, 'url'):
                    raise instaloader.exceptions.InstaloaderException("Post metadata is incomplete")
                
                if post.is_video:
                    if not post.video_url:
                        raise instaloader.exceptions.InstaloaderException("Video URL not found")
                    return post.video_url, 'mp4'
                else:
                    if not post.url:
                        raise instaloader.exceptions.InstaloaderException("Image URL not found")
                    return post.url, 'jpg'
                    
            except Exception as e:
                logger.error(f"Download attempt failed: {str(e)}")
                raise
                
        media_url, media_type = await retry_with_backoff(download_attempt)
        
        return {
            "success": True,
            "media_url": media_url,
            "media_type": media_type
        }
            
    except Exception as e:
        logger.error(f"Error processing URL {url}: {str(e)}")
        return {"success": False, "error": str(e)}

@app.post("/api/download")
async def handle_download(request: Request, download_req: DownloadRequest):
    """Download endpoint'i"""
    try:
        client_id = request.client.host
        task_id = str(uuid.uuid4())
        
        task_manager.add_task(task_id)
        
        result = await download_media_from_instagram(download_req.url, client_id)
        
        task_manager.update_task(task_id, "completed", result)
        
        return {"task_id": task_id, "status": "processing"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """İndirme durumunu kontrol et"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task bulunamadı")
    
    return {
        "task_id": task_id,
        "status": "SUCCESS" if task["status"] == "completed" else "PROCESSING",
        "result": task["result"]
    }

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.client.host
    
    if not rate_limiter.is_allowed(client_id):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )
    
    response = await call_next(request)
    return response

@app.get("/api/redis-test")
async def test_redis():
    try:
        # Test value ekle
        test_key = "test:connection"
        redis_client.set(test_key, "OK", ex=60)  # 60 saniyelik TTL
        
        # Değeri oku
        value = redis_client.get(test_key)
        
        # Rate limit sayacını oku
        rate_limits = redis_client.keys("rate_limit:*")
        rate_limit_counts = {
            key: redis_client.zcard(key)
            for key in rate_limits
        }
        
        return {
            "status": "Redis is working",
            "test_value": value,
            "rate_limits": rate_limit_counts
        }
    except Exception as e:
        return {
            "status": "Redis error",
            "error": str(e)
        }

# Templates ve static dosyalar için klasörler
templates = Jinja2Templates(directory="templates")
os.makedirs("downloads", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def get_shortcode_from_url(url: str) -> str:
    """URL'den shortcode çıkar"""
    # URL'yi temizle
    url = url.split('?')[0].rstrip('/')
    
    # Debug log ekle
    logger.debug(f"Processing URL: {url}")
    
    # Story URL'si için özel kontrol
    story_match = re.search(r'instagram\.com/stories/([^/]+)/(\d+)', url)
    if story_match:
        username = story_match.group(1)
        story_id = story_match.group(2)
        logger.debug(f"Story match found - username: {username}, id: {story_id}")
        return f"story_{username}_{story_id}"
    
    # Diğer URL tipleri için kontrol
    patterns = {
        'post': r'/p/([^/]+)',
        'reel': r'/reel/([^/]+)',
        'igtv': r'/tv/([^/]+)',
    }
    
    for media_type, pattern in patterns.items():
        if match := re.search(pattern, url):
            logger.debug(f"Matched pattern: {media_type} - {pattern}")
            return match.group(1)
    
    logger.warning(f"No pattern matched for URL: {url}")
    return None

@app.get('/api/download-media')
async def download_media(request: Request):
    try:
        media_url = request.query_params.get('url')
        if not media_url:
            raise HTTPException(status_code=400, detail='Media URL is required')

        # Medya dosyasını indir
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url) as response:
                if response.status != 200:
                    raise HTTPException(status_code=400, detail='Failed to download media')

                # Dosya adını belirle
                filename = media_url.split('/')[-1]
                if not filename:
                    content_type = response.headers.get('content-type', '')
                    ext = 'mp4' if 'video' in content_type else 'jpg'
                    filename = f'download.{ext}'

                # Medyayı memory buffer'a al
                buffer = io.BytesIO(await response.read())
                buffer.seek(0)

                return StreamingResponse(
                    buffer,
                    media_type=response.headers.get('content-type', 'application/octet-stream'),
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"'
                    }
                )

    except Exception as e:
        logger.error(f"Media download error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stories/{username}")
async def get_user_stories(username: str):
    """Kullanıcının story'lerini listele"""
    max_retries = 5
    last_error = None

    for attempt in range(max_retries):
        try:
            # Her denemede yeni bir cookie al
            new_cookies = cookie_manager.get_next_cookie()
            if not new_cookies:
                raise HTTPException(status_code=429, detail="Tüm cookie'ler kullanımda veya dinleniyor. Lütfen birkaç dakika sonra tekrar deneyin.")
            
            # Instagram API'sine direkt istek at
            headers = {
                'authority': 'www.instagram.com',
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'origin': 'https://www.instagram.com',
                'referer': f'https://www.instagram.com/{username}/stories/',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'x-asbd-id': '129477',
                'x-csrftoken': new_cookies.get('csrftoken', ''),
                'x-ig-app-id': '936619743392459',
                'x-ig-www-claim': '0',
                'x-requested-with': 'XMLHttpRequest',
                'x-instagram-ajax': '1'
            }
            
            cookies_dict = {
                'sessionid': new_cookies.get('sessionid'),
                'csrftoken': new_cookies.get('csrftoken'),
                'ds_user_id': new_cookies.get('ds_user_id'),
                'ig_did': new_cookies.get('ig_did'),
                'rur': new_cookies.get('rur')
            }

            async with aiohttp.ClientSession() as session:
                # Story'leri al
                user_lookup_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
                
                async with session.get(user_lookup_url, headers=headers, cookies=cookies_dict) as response:
                    response_text = await response.text()
                    
                    if "rate_limit" in response_text.lower():
                        logger.warning(f"Rate limit detected for cookie")
                        cookie_manager.mark_cookie_rate_limited(new_cookies)
                        if attempt < max_retries - 1:
                            continue
                        last_error = "Rate limit aşıldı"
                    
                    if response.status == 200:
                        try:
                            user_data = json.loads(response_text)
                            if 'data' in user_data and 'user' in user_data['data']:
                                user_id = user_data['data']['user']['id']
                                
                                stories_url = f"https://www.instagram.com/api/v1/feed/reels_media/?reel_ids={user_id}"
                                async with session.get(stories_url, headers=headers, cookies=cookies_dict) as story_response:
                                    story_text = await story_response.text()
                                    
                                    if story_response.status == 200:
                                        try:
                                            story_data = json.loads(story_text)
                                            
                                            if 'reels' not in story_data or str(user_id) not in story_data['reels']:
                                                if attempt < max_retries - 1:
                                                    continue
                                                return {
                                                    "success": True,
                                                    "username": username,
                                                    "stories": [],
                                                    "message": "Kullanıcının aktif story'si bulunmuyor"
                                                }
                                            
                                            story_list = []
                                            items = story_data['reels'][str(user_id)].get('items', [])
                                            
                                            if not items and attempt < max_retries - 1:
                                                continue
                                            
                                            for item in items:
                                                story_info = {
                                                    "id": item['id'],
                                                    "type": "video" if item.get('video_versions') else "photo",
                                                    "timestamp": datetime.fromtimestamp(item['taken_at']).isoformat(),
                                                }
                                                
                                                if item.get('video_versions'):
                                                    story_info["url"] = item['video_versions'][0]['url']
                                                    story_info["thumbnail"] = item['image_versions2']['candidates'][0]['url']
                                                else:
                                                    candidates = item['image_versions2']['candidates']
                                                    best_quality = max(candidates, key=lambda x: x['width'] * x['height'])
                                                    story_info["url"] = best_quality['url']
                                                    story_info["thumbnail"] = best_quality['url']
                                                
                                                story_list.append(story_info)
                                            
                                            if story_list:
                                                # Başarılı işlem
                                                cookie_manager.mark_cookie_success(new_cookies)
                                                return {
                                                    "success": True,
                                                    "username": username,
                                                    "stories": story_list
                                                }
                                            elif attempt < max_retries - 1:
                                                continue
                                            else:
                                                return {
                                                    "success": True,
                                                    "username": username,
                                                    "stories": [],
                                                    "message": "Kullanıcının aktif story'si bulunmuyor"
                                                }
                                        except json.JSONDecodeError:
                                            if attempt < max_retries - 1:
                                                continue
                                            last_error = "Story verisi alınamadı"
                                    else:
                                        if attempt < max_retries - 1:
                                            continue
                                        last_error = f"Story'ler alınamadı: {story_text}"
                        except json.JSONDecodeError:
                            if attempt < max_retries - 1:
                                continue
                            last_error = "Kullanıcı bilgileri alınamadı"
                    
                    elif response.status == 400 and "checkpoint_required" in response_text:
                        logger.error(f"Checkpoint required for cookie")
                        cookie_manager.mark_cookie_challenge(new_cookies)
                        if attempt < max_retries - 1:
                            continue
                        last_error = "Oturum doğrulama gerekiyor"
                    
                    elif response.status == 401:
                        if attempt < max_retries - 1:
                            continue
                        last_error = "Oturum geçersiz"
                    
                    else:
                        if attempt < max_retries - 1:
                            continue
                        last_error = f"Kullanıcı bilgileri alınamadı: {response_text}"

        except Exception as e:
            logger.error(f"Error with cookie: {str(e)}")
            if attempt < max_retries - 1:
                continue
            last_error = str(e)

    # Tüm denemeler başarısız oldu
    raise HTTPException(
        status_code=401,
        detail=f"Story'ler alınamadı. Lütfen birkaç dakika sonra tekrar deneyin. Son hata: {last_error}"
    )

@app.get("/api/proxy-image")
async def proxy_image(url: str):
    """Resim proxy endpoint'i"""
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            # Her denemede yeni bir cookie al
            new_cookies = cookie_manager.get_next_cookie()
            if not new_cookies:
                raise HTTPException(status_code=429, detail="Tüm cookie'ler kullanımda veya dinleniyor. Lütfen birkaç dakika sonra tekrar deneyin.")
            
            # Instagram için gerekli header'ları ayarla
            headers = {
                'authority': 'www.instagram.com',
                'accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'accept-language': 'en-US,en;q=0.9',
                'origin': 'https://www.instagram.com',
                'referer': 'https://www.instagram.com/',
                'sec-fetch-dest': 'image',
                'sec-fetch-mode': 'no-cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            cookies_dict = {k: v for k, v in new_cookies.items()}
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url, headers=headers, cookies=cookies_dict, allow_redirects=True, timeout=30) as response:
                        if response.status == 200:
                            cookie_manager.mark_cookie_success(new_cookies)
                            image_data = await response.read()
                            return Response(
                                content=image_data,
                                media_type=response.headers.get('content-type', 'image/jpeg')
                            )
                        elif response.status == 403:
                            cookie_manager.mark_cookie_challenge(new_cookies)
                            if attempt < max_retries - 1:
                                continue
                            last_error = "Oturum geçersiz"
                        else:
                            if attempt < max_retries - 1:
                                continue
                            last_error = f"Failed to fetch image: {response.status}"
                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        continue
                    last_error = "Request timed out"
                except Exception as e:
                    if attempt < max_retries - 1:
                        continue
                    last_error = str(e)
        
        except Exception as e:
            if attempt < max_retries - 1:
                continue
            last_error = str(e)
    
    raise HTTPException(status_code=500, detail=f"Image proxy error: {last_error}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 