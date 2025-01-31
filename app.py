from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
            
    async def get_loader(self):
        async with self.lock:
            loader = self.pool[self.current]
            self.current = (self.current + 1) % self.pool_size
            return loader

loader_pool = InstaloaderPool()

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

def load_cookies_from_file():
    """Cookie dosyasından Instagram oturumunu yükle"""
    try:
        if os.path.exists('instagram_cookies.json'):
            with open('instagram_cookies.json', 'r') as f:
                cookies = json.load(f)
                
            if all(key in cookies for key in ['sessionid', 'csrftoken', 'ds_user_id']):
                # Oturumu temizle
                L.context._session.cookies.clear()
                
                # Cookie'leri yükle
                for key, value in cookies.items():
                    L.context._session.cookies.set(
                        key,
                        value,
                        domain='.instagram.com',
                        path='/'
                    )
                
                # Kullanıcı ID'sini ayarla
                L.context.user_id = cookies.get('ds_user_id')
                L.context.username = INSTAGRAM_USERNAME
                
                # Test connection - sadece cookie kontrolü yap
                if L.context.is_logged_in:
                    print("Cookie ile giriş başarılı!")
                    return True
                else:
                    print("Cookie geçersiz.")
                    return False
                    
    except Exception as e:
        print(f"Cookie yükleme hatası: {str(e)}")
    return False

def instagram_login():
    """Instagram'a giriş yap"""
    try:
        # Cookie dosyasından giriş yapmayı dene
        if load_cookies_from_file():
            return True
            
        print("\n=== Instagram Giriş Talimatları ===")
        print("1. Tarayıcınızda Instagram'a giriş yapın")
        print("2. DevTools'u açın (Safari -> Develop -> Show Web Inspector)")
        print("3. Storage -> Cookies -> instagram.com'a gidin")
        print("4. Aşağıdaki cookie değerlerini kopyalayıp instagram_cookies.json dosyasına kaydedin:")
        print("   - sessionid")
        print("   - csrftoken")
        print("   - ds_user_id")
        print("   - mid (opsiyonel)")
        print("   - ig_did (opsiyonel)")
        print("\nÖrnek format:")
        print("""
{
    "sessionid": "your-session-id",
    "csrftoken": "your-csrf-token",
    "ds_user_id": "your-user-id",
    "mid": "your-mid",
    "ig_did": "your-ig-did"
}
        """)
        print("\nDosyayı kaydettikten sonra uygulamayı yeniden başlatın.")
        return False
            
    except Exception as e:
        print(f"Instagram giriş hatası: {str(e)}")
        return False

# Instagram'a giriş yap
if not instagram_login():
    print("Instagram bağlantısı kurulamadı. Cookie dosyasını oluşturun ve tekrar deneyin.")

# Templates ve static dosyalar için klasörler
templates = Jinja2Templates(directory="templates")
os.makedirs("downloads", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

class DownloadRequest(BaseModel):
    url: str
    type: Optional[str] = "post"  # post, reel, story, igtv

def get_shortcode_from_url(url: str) -> str:
    """URL'den shortcode çıkar"""
    patterns = [
        r'/p/([^/]+)/',
        r'/reel/([^/]+)/',
        r'/tv/([^/]+)/',
    ]
    
    for pattern in patterns:
        if match := re.search(pattern, url):
            return match.group(1)
    return None

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
            logger.warning(
                f"Rate limit exceeded for client: {client_id}",
                extra=extra
            )
            return {"success": False, "error": "Rate limit aşıldı. Lütfen biraz bekleyin."}
        
        shortcode = get_shortcode_from_url(url)
        if not shortcode:
            logger.warning(
                f"Invalid Instagram URL: {url}",
                extra=extra
            )
            return {"success": False, "error": "Geçerli bir Instagram URL'si değil"}
        
        try:
            # Pool'dan loader al
            loader = await loader_pool.get_loader()
            
            logger.debug(
                f"Processing Instagram URL: {url}, shortcode: {shortcode}",
                extra=extra
            )
            
            # Post'u al
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            
            # Video veya resim URL'sini al
            if post.is_video:
                media_url = post.video_url
                media_type = 'mp4'
            else:
                media_url = post.url
                media_type = 'jpg'
            
            # İşlem süresini hesapla
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            extra['response_time'] = response_time
            
            logger.info(
                f"Successfully processed Instagram URL: {url}",
                extra=extra
            )
            
            return {
                "success": True,
                "media_url": media_url,
                "media_type": media_type
            }
            
        except instaloader.exceptions.InstaloaderException as e:
            error_msg = str(e)
            
            # İşlem süresini hesapla
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            extra['response_time'] = response_time
            extra['status_code'] = 400
            
            logger.error(
                f"Instagram error for URL {url}: {error_msg}\n"
                f"Traceback: {traceback.format_exc()}",
                extra=extra
            )
            
            return {"success": False, "error": f"Instagram hatası: {error_msg}"}
                
    except Exception as e:
        # İşlem süresini hesapla
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        extra['response_time'] = response_time
        extra['status_code'] = 500
        
        logger.error(
            f"General error for URL {url}: {str(e)}\n"
            f"Traceback: {traceback.format_exc()}",
            extra=extra
        )
        
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 