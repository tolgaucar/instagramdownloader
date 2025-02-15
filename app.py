from fastapi import FastAPI, HTTPException, Request, Form, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response, HTMLResponse, RedirectResponse
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
from starlette.middleware.sessions import SessionMiddleware
from models import (
    Session, Language, Translation, Admin,
    init_db, add_language, get_language, get_translations_for_language,
    update_translation, add_admin, get_admin, update_admin_last_login,
    delete_admin, get_all_admins, verify_admin_password, update_admin_password
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import jwt

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
    url: str  # Only URL is needed, type will be auto-detected

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
        self.cookies_dir = "cookies"
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD', None),
            decode_responses=True
        )
        
        if not os.path.exists(self.cookies_dir):
            os.makedirs(self.cookies_dir)

    def load_cookies(self):
        """Tüm cookie'leri yeniden yükle"""
        try:
            cookie_files = [f for f in os.listdir(self.cookies_dir) if f.endswith('.json')]
            
            for cookie_file in cookie_files:
                cookie_id = cookie_file.replace('.json', '')
                cookie_path = os.path.join(self.cookies_dir, cookie_file)
                
                try:
                    with open(cookie_path, 'r') as f:
                        cookie_data = json.load(f)
                        
                        # Cookie sağlık durumunu kontrol et, yoksa oluştur
                        health_key = self._get_cookie_health_key(cookie_id)
                        if not self.redis_client.exists(health_key):
                            self.redis_client.hset(health_key, mapping={
                                'successes': '0',
                                'challenges': '0',
                                'last_success': '',
                                'last_challenge': ''
                            })
                except Exception as e:
                    logger.error(f"Error loading cookie {cookie_id}: {str(e)}")
                    continue
                    
            logger.info("Cookies reloaded successfully")
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            raise

    @property
    def cookies(self) -> list:
        """Tüm cookie'leri ve durumlarını getir"""
        return self.get_cookies()

    def get_cookies(self) -> list:
        """Tüm cookie'leri ve durumlarını getir"""
        cookies = []
        try:
            cookie_files = [f for f in os.listdir(self.cookies_dir) if f.endswith('.json')]
            
            for cookie_file in cookie_files:
                cookie_id = cookie_file.replace('.json', '')
                
                # Cookie durumunu kontrol et
                cooldown = self.is_cookie_in_cooldown(cookie_id)
                health = self.get_cookie_health(cookie_id)
                
                cookies.append({
                    'id': cookie_id,
                    'cooldown': cooldown,
                    'health': health
                })
            
            return cookies
        except Exception as e:
            logger.error(f"Error getting cookies: {str(e)}")
            return []

    def _get_cookie_health_key(self, cookie_id: str) -> str:
        return f"cookie:{cookie_id}:health"

    def _get_cookie_cooldown_key(self, cookie_id: str) -> str:
        return f"cookie:{cookie_id}:cooldown"

    def _get_request_count_key(self, cookie_id: str) -> str:
        return f"cookie:{cookie_id}:requests"

    def get_cookie_health(self, cookie_id: str) -> dict:
        health_key = self._get_cookie_health_key(cookie_id)
        health_data = self.redis_client.hgetall(health_key)
        return {k: v for k, v in health_data.items()} if health_data else {
            'successes': '0',
            'challenges': '0',
            'last_success': '',
            'last_challenge': ''
        }
    

    def is_cookie_in_cooldown(self, cookie_id: str) -> bool:
        cooldown_key = self._get_cookie_cooldown_key(cookie_id)
        cooldown = self.redis_client.get(cooldown_key)
        if cooldown:
            cooldown_time = float(cooldown)
            if cooldown_time > datetime.now().timestamp():
                return True
        return False

    def get_next_cookie(self) -> dict:
        """Get the next available cookie with improved selection"""
        try:
            cookie_files = [f for f in os.listdir(self.cookies_dir) if f.endswith('.json')]
            available_cookies = []

            for cookie_file in cookie_files:
                cookie_id = cookie_file.replace('.json', '')
                
                # Skip if cookie is in cooldown
                if self.is_cookie_in_cooldown(cookie_id):
                    logger.debug(f"Cookie {cookie_id} is in cooldown")
                    continue

                # Get cookie health
                health = self.get_cookie_health(cookie_id)
                successes = int(health.get('successes', 0))
                challenges = int(health.get('challenges', 0))
                
                # Calculate success rate
                total_requests = successes + challenges
                success_rate = (successes / total_requests * 100) if total_requests > 0 else 100
                
                # Skip if cookie has poor health (less than 20% success rate)
                if total_requests > 5 and success_rate < 20:
                    logger.debug(f"Cookie {cookie_id} has poor health (success rate: {success_rate}%)")
                    continue

                try:
                    with open(os.path.join(self.cookies_dir, cookie_file), 'r') as f:
                        cookie_data = json.load(f)
                        # Add last success time bonus
                        last_success = health.get('last_success')
                        time_bonus = 0
                        if last_success:
                            last_success_time = datetime.fromisoformat(last_success)
                            minutes_since_success = (datetime.now() - last_success_time).total_seconds() / 60
                            time_bonus = min(minutes_since_success / 10, 50)  # Max 50 point bonus for time
                        
                        final_score = success_rate + time_bonus
                        available_cookies.append((cookie_data, final_score))
                except Exception as e:
                    logger.error(f"Error loading cookie {cookie_id}: {str(e)}")
                    continue

            if not available_cookies:
                logger.warning("No available cookies found")
                return None

            # Sort by score and pick randomly from top 3
            available_cookies.sort(key=lambda x: x[1], reverse=True)
            top_cookies = available_cookies[:min(3, len(available_cookies))]
            selected_cookie = random.choice(top_cookies)[0]
            
            logger.info(f"Selected cookie with score {top_cookies[0][1]}")
            return selected_cookie
            
        except Exception as e:
            logger.error(f"Error getting next cookie: {str(e)}")
            return None

    def mark_cookie_success(self, cookie_data: dict):
        """Mark a cookie as successful"""
        try:
            cookie_id = cookie_data.get('ds_user_id')
            if not cookie_id:
                return
            
            health_key = self._get_cookie_health_key(cookie_id)
            self.redis_client.hincrby(health_key, 'successes', 1)
            self.redis_client.hset(health_key, 'last_success', datetime.now().isoformat())
            
            # Remove cooldown if exists
            cooldown_key = self._get_cookie_cooldown_key(cookie_id)
            self.redis_client.delete(cooldown_key)
            
            logger.info(f"Cookie {cookie_id} marked as successful")
        except Exception as e:
            logger.error(f"Error marking cookie success: {str(e)}")

    def mark_cookie_challenge(self, cookie_data: dict):
        """Mark a cookie as challenged with progressive cooldown"""
        try:
            cookie_id = cookie_data.get('ds_user_id')
            if not cookie_id:
                return
            
            health_key = self._get_cookie_health_key(cookie_id)
            challenges = int(self.redis_client.hincrby(health_key, 'challenges', 1))
            self.redis_client.hset(health_key, 'last_challenge', datetime.now().isoformat())
            
            # Calculate cooldown duration based on challenge count
            cooldown_minutes = min(30 * (2 ** (challenges - 1)), 720)  # Max 12 hours
            cooldown_time = datetime.now() + timedelta(minutes=cooldown_minutes)
            
            cooldown_key = self._get_cookie_cooldown_key(cookie_id)
            self.redis_client.set(cooldown_key, cooldown_time.timestamp())
            
            logger.warning(f"Cookie {cookie_id} challenged. Cooldown: {cooldown_minutes} minutes")
        except Exception as e:
            logger.error(f"Error marking cookie challenge: {str(e)}")

    def mark_cookie_rate_limited(self, cookie_data: dict):
        """Mark a cookie as rate limited with progressive cooldown"""
        try:
            cookie_id = cookie_data.get('ds_user_id')
            if not cookie_id:
                return
            
            # Get current rate limit count
            rate_limit_key = f"cookie:{cookie_id}:rate_limits"
            rate_limits = self.redis_client.incr(rate_limit_key)
            self.redis_client.expire(rate_limit_key, 86400)  # Expire after 24 hours
            
            # Calculate cooldown duration based on rate limit count
            cooldown_minutes = min(15 * (2 ** (rate_limits - 1)), 360)  # Max 6 hours
            cooldown_time = datetime.now() + timedelta(minutes=cooldown_minutes)
            
            cooldown_key = self._get_cookie_cooldown_key(cookie_id)
            self.redis_client.set(cooldown_key, cooldown_time.timestamp())
            
            logger.warning(f"Cookie {cookie_id} rate limited. Cooldown: {cooldown_minutes} minutes")
        except Exception as e:
            logger.error(f"Error marking cookie rate limited: {str(e)}")

# Global instances
load_dotenv()

# Redis connection settings
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Redis client
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True
)

class RedisRateLimiter:
    def __init__(self, max_requests=100, time_window=60):
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD', None)
        )
        self.max_requests = max_requests
        self.time_window = time_window
        
    async def is_rate_limited(self, key: str) -> bool:
        try:
            current = self.redis_client.get(key)
            if current is None:
                self.redis_client.setex(key, self.time_window, 1)
                return False
            
            count = int(current)
            if count >= self.max_requests:
                return True
            
            self.redis_client.incr(key)
            return False
        except Exception as e:
            print(f"Rate limiter error: {str(e)}")
            return False

    def get_remaining_requests(self, key: str) -> int:
        try:
            current = self.redis_client.get(key)
            if current is None:
                return self.max_requests
            return max(0, self.max_requests - int(current))
        except Exception as e:
            print(f"Error getting remaining requests: {str(e)}")
            return 0

class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD', None)
        )

    def add_task(self, task_id: str):
        """Yeni task ekle"""
        self.tasks[task_id] = {
            "status": "processing",
            "result": None,
            "created_at": datetime.now().timestamp()
        }
        
    def update_task(self, task_id: str, status: str, result: dict = None):
        """Task durumunu güncelle"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["result"] = result
            
    def get_task(self, task_id: str) -> dict:
        """Task bilgilerini getir"""
        return self.tasks.get(task_id)
        
    def cleanup_old_tasks(self, max_age: int = 3600):
        """Eski taskları temizle"""
        current_time = datetime.now().timestamp()
        self.tasks = {
            task_id: task_data
            for task_id, task_data in self.tasks.items()
            if current_time - task_data["created_at"] < max_age
        }

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

# Templates ve static dosyalar için klasörler
templates = Jinja2Templates(directory="templates")
os.makedirs("downloads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

# Admin kimlik doğrulama
def get_current_admin_from_token(admin_token: str = Cookie(None)):
    """JWT token'dan admin bilgilerini al"""
    if not admin_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = jwt.decode(admin_token, "your-secret-key", algorithms=["HS256"])
        admin = get_admin(payload["sub"])
        if not admin:
            raise HTTPException(status_code=401, detail="Invalid token")
        return admin
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Admin login için rate limit
class AdminLoginRateLimiter:
    def __init__(self, redis_client, max_attempts=5, window_minutes=15, lockout_minutes=30):
        self.redis = redis_client
        self.max_attempts = max_attempts
        self.window_minutes = window_minutes
        self.lockout_minutes = lockout_minutes

    def _get_attempt_key(self, username: str, ip: str) -> str:
        return f"admin_login_attempts:{username}:{ip}"

    def _get_lockout_key(self, username: str, ip: str) -> str:
        return f"admin_login_lockout:{username}:{ip}"

    def is_locked_out(self, username: str, ip: str) -> bool:
        lockout_key = self._get_lockout_key(username, ip)
        return bool(self.redis.get(lockout_key))

    def record_attempt(self, username: str, ip: str, success: bool):
        attempt_key = self._get_attempt_key(username, ip)
        lockout_key = self._get_lockout_key(username, ip)

        if success:
            # Başarılı girişte tüm kayıtları temizle
            self.redis.delete(attempt_key, lockout_key)
            return

        # Başarısız girişi kaydet
        attempts = self.redis.incr(attempt_key)
        self.redis.expire(attempt_key, self.window_minutes * 60)

        # Maksimum deneme sayısı aşıldıysa kilitle
        if attempts >= self.max_attempts:
            self.redis.setex(lockout_key, self.lockout_minutes * 60, "1")
            self.redis.delete(attempt_key)

    def get_remaining_attempts(self, username: str, ip: str) -> int:
        """Kalan deneme sayısını döndür"""
        try:
            attempt_key = self._get_attempt_key(username, ip)
            attempts = int(self.redis.get(attempt_key) or 0)
            return max(0, self.max_attempts - attempts)
        except Exception as e:
            logger.error(f"Error getting remaining attempts: {str(e)}")
            return 0

# Rate limiter instance'ı oluştur
admin_login_limiter = AdminLoginRateLimiter(redis_client)

# Admin login sayfası
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str = None):
    """Admin login sayfası"""
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": error}
    )

# Admin login işlemi
@app.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """Admin login işlemi"""
    client_ip = request.client.host

    # Brute force koruması
    if admin_login_limiter.is_locked_out(username, client_ip):
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": f"Çok fazla başarısız deneme. Lütfen {admin_login_limiter.lockout_minutes} dakika bekleyin."
            }
        )

    admin = get_admin(username)
    if not admin or not verify_admin_password(admin, password):
        # Başarısız girişi kaydet
        admin_login_limiter.record_attempt(username, client_ip, success=False)
        remaining = admin_login_limiter.get_remaining_attempts(username, client_ip)
        
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": f"Geçersiz kullanıcı adı veya şifre. Kalan deneme hakkı: {remaining}"
            }
        )
    
    # Başarılı girişi kaydet
    admin_login_limiter.record_attempt(username, client_ip, success=True)
    
    # JWT token oluştur
    token_data = {
        "sub": admin.username,
        "id": admin.id,
        "exp": datetime.utcnow() + timedelta(days=1)
    }
    token = jwt.encode(token_data, "your-secret-key", algorithm="HS256")
    
    # Son giriş zamanını güncelle
    update_admin_last_login(admin.id)
    
    # Token'ı cookie olarak kaydet ve yönlendir
    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        max_age=86400,  # 1 gün
        secure=False  # HTTPS için True yapılmalı
    )
    return response

# Admin sayfası - token ile authentication
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(
    request: Request,
    admin: Admin = Depends(get_current_admin_from_token)
):
    """Admin panel sayfası"""
    try:
        # Aktif dilleri getir
        languages = get_languages()
        
        # Cookie bilgilerini getir
        cookies = cookie_manager.get_cookies()
        
        # Admin listesini getir
        admins = get_all_admins()
        
        return templates.TemplateResponse(
            "admin.html",
            {
                "request": request,
                "languages": languages,
                "cookies": cookies,
                "admins": admins,
                "current_admin": admin
            }
        )
    except Exception as e:
        logger.error(f"Admin panel error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Admin logout
@app.get("/admin/logout")
async def admin_logout():
    """Admin logout işlemi"""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response

# Admin yönetimi endpoint'leri
@app.post("/api/admin/admins")
async def add_admin_endpoint(
    request: Request,
    admin_token: str = Cookie(None)
):
    """Yeni admin ekle"""
    if not admin_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    try:
        # Token'ı doğrula
        try:
            payload = jwt.decode(admin_token, "your-secret-key", algorithms=["HS256"])
            admin = get_admin(payload["sub"])
            if not admin:
                raise HTTPException(status_code=401, detail="Invalid token")
        except (jwt.ExpiredSignatureError, jwt.JWTError):
            raise HTTPException(status_code=401, detail="Invalid token")
            
        data = await request.json()
        username = data.get('username')
        password = data.get('password')
        
        if not all([username, password]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        new_admin = add_admin(username, password)
        return {"success": True, "admin": {
            "id": new_admin.id,
            "username": new_admin.username,
            "created_at": new_admin.created_at.isoformat()
        }}
    except Exception as e:
        logger.error(f"Add admin error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/admins/{admin_id}")
async def delete_admin_endpoint(
    admin_id: int,
    admin_token: str = Cookie(None)
):
    """Admin sil"""
    if not admin_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    try:
        # Token'ı doğrula
        try:
            payload = jwt.decode(admin_token, "your-secret-key", algorithms=["HS256"])
            admin = get_admin(payload["sub"])
            if not admin:
                raise HTTPException(status_code=401, detail="Invalid token")
        except (jwt.ExpiredSignatureError, jwt.JWTError):
            raise HTTPException(status_code=401, detail="Invalid token")
            
        if admin.id == admin_id:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")
        
        delete_admin(admin_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Delete admin error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Dil yönetimi endpoint'leri
@app.post("/api/admin/languages")
async def add_language_endpoint(
    request: Request,
    username: str = Depends(get_current_admin_from_token)
):
    """Yeni dil ekle"""
    try:
        data = await request.json()
        code = data.get('code')
        name = data.get('name')
        flag = data.get('flag')
        
        if not all([code, name, flag]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        language = add_language(code, name, flag)
        return {"success": True, "language": {
            "code": language.code,
            "name": language.name,
            "flag": language.flag
        }}
    except Exception as e:
        logger.error(f"Add language error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/translations/{lang_code}")
async def get_translations_endpoint(
    lang_code: str,
    username: str = Depends(get_current_admin_from_token)
):
    """Dil çevirilerini getir"""
    try:
        translations = get_translations(lang_code)
        return translations
    except Exception as e:
        logger.error(f"Get translations error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/translations/{lang_code}")
async def update_translations_endpoint(
    lang_code: str,
    request: Request,
    username: str = Depends(get_current_admin_from_token)
):
    """Dil çevirilerini güncelle"""
    try:
        data = await request.json()
        translations = data.get('translations')
        
        if not translations:
            raise HTTPException(status_code=400, detail="No translations provided")
        
        language = get_language(lang_code)
        if not language:
            raise HTTPException(status_code=404, detail="Language not found")
        
        # Çevirileri güncelle
        for key, value in translations.items():
            update_translation(language.id, key, value)
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Update translations error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Cookie yönetimi endpoint'leri
@app.post("/api/admin/cookies")
async def add_cookie_endpoint(
    request: Request,
    username: str = Depends(get_current_admin_from_token)
):
    """Yeni cookie ekle"""
    try:
        data = await request.json()
        cookie_id = data.get('id')
        cookie_data = data.get('data')
        
        if not all([cookie_id, cookie_data]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # Cookie dosyasını kaydet
        cookie_path = Path("cookies") / f"{cookie_id}.json"
        cookie_path.parent.mkdir(exist_ok=True)
        
        with open(cookie_path, 'w') as f:
            json.dump(cookie_data, f, indent=2)
        
        # Cookie manager'ı yeniden yükle
        cookie_manager.load_cookies()
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Add cookie error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/cookies/{cookie_id}")
async def delete_cookie_endpoint(
    cookie_id: str,
    username: str = Depends(get_current_admin_from_token)
):
    """Cookie sil"""
    try:
        cookie_path = Path("cookies") / f"{cookie_id}.json"
        if not cookie_path.exists():
            raise HTTPException(status_code=404, detail="Cookie not found")
        
        # Redis'teki cookie verilerini temizle
        health_key = cookie_manager._get_cookie_health_key(cookie_id)
        cooldown_key = cookie_manager._get_cookie_cooldown_key(cookie_id)
        request_key = cookie_manager._get_request_count_key(cookie_id)
        
        redis_client.delete(health_key, cooldown_key, request_key)
        
        # Cookie dosyasını sil
        cookie_path.unlink()
        
        # Cookie manager'ı yeniden yükle
        cookie_manager.load_cookies()
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Delete cookie error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/cookies")
async def get_cookies_endpoint(
    username: str = Depends(get_current_admin_from_token)
):
    try:
        cookie_manager = CookieManager()
        cookies = cookie_manager.get_cookies()
        
        return cookies
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/system-status", response_class=HTMLResponse, include_in_schema=True)
async def system_status(
    request: Request,
    admin: Admin = Depends(get_current_admin_from_token)
):
    """Sistem durumu sayfası - Sadece admin erişebilir"""
    try:
        # Redis durumunu kontrol et
        redis_status = {"status": "OK", "error": None}
        try:
            redis_client.ping()
            # Rate limit sayacını oku
            rate_limits = redis_client.keys("rate_limit:*")
            rate_limit_counts = {
                key: redis_client.zcard(key)
                for key in rate_limits
            }
            redis_status["rate_limits"] = rate_limit_counts
        except Exception as e:
            redis_status = {"status": "ERROR", "error": str(e)}

        # Cookie durumunu kontrol et
        cookie_status = {"status": "OK", "error": None}
        try:
            cookies = []
            for cookie in cookie_manager.cookies:
                cookie_id = cookie['id']
                health_key = cookie_manager._get_cookie_health_key(cookie_id)
                cooldown_key = cookie_manager._get_cookie_cooldown_key(cookie_id)
                request_key = cookie_manager._get_request_count_key(cookie_id)
                
                health = redis_client.hgetall(health_key) or {}
                cooldown = redis_client.get(cooldown_key)
                request_count = redis_client.zcard(request_key)
                
                cookies.append({
                    "id": cookie_id,
                    "health": health,
                    "cooldown": cooldown,
                    "request_count": request_count
                })
            cookie_status["cookies"] = cookies
        except Exception as e:
            cookie_status = {"status": "ERROR", "error": str(e)}

        # Sistem kaynaklarını kontrol et
        import psutil
        system_resources = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory": {
                "total": psutil.virtual_memory().total,
                "available": psutil.virtual_memory().available,
                "percent": psutil.virtual_memory().percent
            },
            "disk": {
                "total": psutil.disk_usage('/').total,
                "used": psutil.disk_usage('/').used,
                "free": psutil.disk_usage('/').free,
                "percent": psutil.disk_usage('/').percent
            }
        }

        # Log dosyalarının durumunu kontrol et
        log_status = {"status": "OK", "error": None}
        try:
            log_files = {
                "general": os.path.getsize("logs/instatest.log"),
                "error": os.path.getsize("logs/error.log"),
                "debug": os.path.getsize("logs/debug.log")
            }
            log_status["files"] = log_files
        except Exception as e:
            log_status = {"status": "ERROR", "error": str(e)}

        # Son hataları getir
        last_errors = []
        try:
            with open("logs/error.log", "r") as f:
                errors = f.readlines()[-10:]  # Son 10 hata
                last_errors = [error.strip() for error in errors]
        except Exception as e:
            last_errors = [f"Error reading log file: {str(e)}"]

        # Veritabanı durumunu kontrol et
        db_status = {"status": "OK", "error": None}
        try:
            session = Session()
            language_count = session.query(Language).count()
            translation_count = session.query(Translation).count()
            db_status["stats"] = {
                "languages": language_count,
                "translations": translation_count
            }
        except Exception as e:
            db_status = {"status": "ERROR", "error": str(e)}
        finally:
            session.close()

        # Template'i render et
        return templates.TemplateResponse(
            "system_status.html",
            {
                "request": request,
                "redis_status": redis_status,
                "cookie_status": cookie_status,
                "system_resources": system_resources,
                "log_status": log_status,
                "last_errors": last_errors,
                "db_status": db_status
            },
            headers={"Cache-Control": "no-store"}  # Önbelleklemeyi devre dışı bırak
        )
    except Exception as e:
        logger.error(f"System status page error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

# Middleware for request logging and language redirection
@app.middleware("http")
async def combined_middleware(request: Request, call_next):
    # Request başlangıç zamanı
    start_time = time.time()
    
    # Sistem durumu ve admin sayfası için yönlendirme yapma
    if request.url.path in ["/system-status", "/admin"]:
        return await call_next(request)
    
    response = await call_next(request)
    
    # Response süresini hesapla ve logla
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    
    # Log formatı
    log_dict = {
        "timestamp": datetime.now().isoformat(),
        "client_ip": request.client.host,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "process_time": process_time
    }
    
    # JSON formatında log
    logger.info(json.dumps(log_dict))
        
    return response

@app.on_event("startup")
async def startup_event():
    logger.info("Application starting up", extra={
        'client_ip': '-',
        'endpoint': 'startup',
        'response_time': 0.0,
        'status_code': 0
    })
    
    # Veritabanını başlat
    init_db()
    
    # Varsayılan admin kullanıcısını ekle
    session = Session()
    try:
        if not session.query(Admin).first():
            admin_username = os.getenv("ADMIN_USERNAME", "admin")
            admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
            add_admin(admin_username, admin_password)
            logger.info("Default admin user created")
    except Exception as e:
        logger.error(f"Error creating default admin: {str(e)}")
    finally:
        session.close()
    
    # Veritabanı boşsa varsayılan dilleri ve çevirileri ekle
    session = Session()
    try:
        if not session.query(Language).first():
            # Varsayılan dilleri ekle
            en = add_language('en', 'English', '🇺🇸')
            tr = add_language('tr', 'Türkçe', '🇹🇷')
            
            # İngilizce çeviriler
            default_en_translations = {
                'site_name': 'InstaTest',
                'title': 'Instagram Media Downloader',
                'subtitle': 'Download Instagram stories, reels, and posts easily',
                'input_placeholder': 'Insert Instagram link here',
                'paste_button': 'Paste',
                'download_button': 'Download',
                'loading_text': 'Processing...',
                'success_text': 'Download completed!',
                'error_text': 'An error occurred',
                'description': 'A powerful tool to download Instagram content with high quality and complete anonymity.',
                'supported_urls_title': 'Supported URLs:',
                'supported_urls_text': 'instagram.com/p/... (posts), instagram.com/reel/... (reels), instagram.com/stories/... (stories)',
                'how_to_title': 'How to download Story from Instagram?',
                'how_to_step1': 'Copy the URL',
                'how_to_step1_desc': 'First, open the Instagram Story you wish to download. Then, click on the (...) icon if you are using an iPhone or (:) if you are using an Android. From the popup menu, select the "Copy Link" option to copy the Story\'s URL.',
                'faq_title': 'Frequently asked questions(FAQ)',
                'faq_desc': 'This FAQ provides information on frequent questions or concerns about the instatest.com downloader. if you can\'t find the answer to your question, feel free to ask through email on our contact page.',
            }
            
            # Türkçe çeviriler
            default_tr_translations = {
                'site_name': 'InstaTest',
                'title': 'Instagram Medya İndirici',
                'subtitle': 'Instagram hikayelerini, reels ve gönderilerini kolayca indirin',
                'input_placeholder': 'Instagram linkini buraya yapıştırın',
                'paste_button': 'Yapıştır',
                'download_button': 'İndir',
                'loading_text': 'İşleniyor...',
                'success_text': 'İndirme tamamlandı!',
                'error_text': 'Bir hata oluştu',
                'description': 'Instagram içeriklerini yüksek kalitede ve tam gizlilikle indirmenizi sağlayan güçlü bir araç.',
                'supported_urls_title': 'Desteklenen URLler:',
                'supported_urls_text': 'instagram.com/p/... (gönderiler), instagram.com/reel/... (reels), instagram.com/stories/... (hikayeler)',
                'how_to_title': 'Instagram\'dan Hikaye nasıl indirilir?',
                'how_to_step1': 'URL\'yi kopyalayın',
                'how_to_step1_desc': 'Önce, indirmek istediğiniz Instagram Hikayesini açın. Ardından, iPhone kullanıyorsanız (...) simgesine veya Android kullanıyorsanız (:) simgesine tıklayın. Açılan menüden "Bağlantıyı Kopyala" seçeneğini seçerek Hikayenin URL\'sini kopyalayın.',
                'faq_title': 'Sık sorulan sorular(SSS)',
                'faq_desc': 'Bu SSS, instatest.com indirici hakkında sık sorulan sorular veya endişeler hakkında bilgi sağlar. Sorunuzun cevabını bulamazsanız, iletişim sayfamızdaki e-posta yoluyla sormaktan çekinmeyin.',
            }
            
            # Çevirileri ekle
            for key, value in default_en_translations.items():
                add_translation(en.id, key, value)
            
            for key, value in default_tr_translations.items():
                add_translation(tr.id, key, value)
            
            logger.info("Default languages and translations added")
    except Exception as e:
        logger.error(f"Error adding default languages and translations: {str(e)}")
    finally:
        session.close()
    
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
            if asyncio.iscoroutinefunction(func):
                return await func()
            else:
                return func()
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
        'url': url
    }
    logger.info(f"Download request received", extra=extra)
    
    current_cookie = None
    try:
        # Get a loader from the pool
        loader = await loader_pool.get_loader()
        current_cookie = loader.context.username
        
        # Get the shortcode from the URL
        shortcode = get_shortcode_from_url(url)
        if not shortcode:
            raise ValueError("Invalid Instagram URL")
        
        async def download_attempt():
            post = None
            try:
                # Post.from_shortcode'u sync olarak çağır
                def get_post():
                    return instaloader.Post.from_shortcode(loader.context, shortcode)
                
                post = await retry_with_backoff(get_post)
            except Exception as e:
                logger.error(f"Error getting post: {str(e)}", extra=extra)
                raise

            if not post:
                raise ValueError("Could not fetch post data")

            # Get media URLs
            media_urls = []
            if post.is_video and post.video_url:
                media_urls.append({
                    'url': post.video_url,
                    'type': 'video',
                    'thumbnail': post.url
                })
            else:
                media_urls.append({
                    'url': post.url,
                    'type': 'image'
                })

            if not media_urls:
                raise ValueError("No media found in post")

            # Mark cookie as successful
            if current_cookie:
                cookie_manager.mark_cookie_success({"id": current_cookie})
            
            return {
                'success': True,
                'media_urls': media_urls,
                'type': 'video' if post.is_video else 'image',
                'caption': post.caption if post.caption else '',
                'owner': post.owner_username,
                'timestamp': post.date_local.isoformat()
            }

        result = await download_attempt()
        return result

    except instaloader.exceptions.ConnectionException as e:
        logger.error(f"Connection error: {str(e)}", extra=extra)
        if "429" in str(e) and current_cookie:  # Rate limit response
            cookie_manager.mark_cookie_rate_limited({"id": current_cookie})
        raise HTTPException(status_code=429, detail="Rate limited. Please try again later.")
    
    except instaloader.exceptions.LoginRequiredException as e:
        logger.error(f"Login required: {str(e)}", extra=extra)
        if current_cookie:
            cookie_manager.mark_cookie_challenge({"id": current_cookie})
        raise HTTPException(status_code=401, detail="Login required to access this content")
            
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}", extra=extra)
        raise HTTPException(status_code=500, detail=f"Failed to download media: {str(e)}")

@app.post("/api/download")
async def handle_download(request: Request, download_req: DownloadRequest):
    """Download endpoint'i"""
    try:
        client_id = request.client.host
        task_id = str(uuid.uuid4())
        
        task_manager.add_task(task_id)
        
        try:
            result = await download_media_from_instagram(download_req.url, client_id)
            task_manager.update_task(task_id, "completed", result)
        
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": result
            }
        except Exception as e:
            task_manager.update_task(task_id, "failed", {"error": str(e)})
            raise HTTPException(status_code=500, detail=str(e))
            
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
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

def get_translations(lang_code: str) -> dict:
    """Belirtilen dil için çevirileri getir"""
    db = Session()
    try:
        translations = {}
        language = db.query(Language).filter_by(code=lang_code, is_active=True).first()
        if language:
            for translation in language.translations:
                translations[translation.key] = translation.value
        return translations
    finally:
        db.close()

def get_languages() -> list:
    """Aktif dilleri getir"""
    db = Session()
    try:
        languages = []
        for lang in db.query(Language).filter_by(is_active=True).all():
            languages.append({
                'code': lang.code,
                'name': lang.name,
                'flag': lang.flag
            })
        return languages
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint - serves English content directly"""
    return await read_root(request, "en")

@app.get("/{lang_code}", response_class=HTMLResponse)
async def read_root(request: Request, lang_code: str):
    """Language specific content"""
    # Dil kodunu kontrol et
    if not get_language(lang_code):
        lang_code = "en"  # Varsayılan dil
        
    translations = get_translations(lang_code)
    languages = get_languages()
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "translations": translations,
            "languages": languages,
            "current_lang": lang_code
        }
    )

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

        # Instagram URL kontrolü
        if 'instagram.com' in media_url and not ('cdninstagram.com' in media_url or 'fbcdn.net' in media_url):
            # Instagram API'sini kullan
            client_id = request.client.host
            result = await download_media_from_instagram(media_url, client_id)
            
            if not result.get('success'):
                raise HTTPException(status_code=400, detail=result.get('error', 'Failed to process Instagram URL'))
            
            media_url = result['media_urls'][0]['url']

        # Medya dosyasını indir
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url) as response:
                if response.status != 200:
                    raise HTTPException(status_code=400, detail='Failed to download media')

                # Dosya adını belirle
                content_type = response.headers.get('content-type', '')
                ext = 'mp4' if 'video' in content_type else 'jpg'
                filename = f'instagram_media_{int(time.time())}.{ext}'

                # Medyayı memory buffer'a al
                buffer = io.BytesIO(await response.read())
                buffer.seek(0)

                return StreamingResponse(
                    buffer,
                    media_type=response.headers.get('content-type', 'application/octet-stream'),
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'Content-Type': content_type,
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0'
                    }
                )

    except HTTPException as he:
        logger.error(f"HTTP error in download_media: {str(he)}")
        raise he
    except Exception as e:
        logger.error(f"Media download error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to download media: {str(e)}")

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
                raise HTTPException(status_code=429, detail="Tüm cookie'ler kullanımda veya dinleniyor")
            
            # Instagram için gerekli header'ları ayarla
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Origin': 'https://www.instagram.com',
                'Referer': 'https://www.instagram.com/',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
                'Connection': 'keep-alive'
            }
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url, headers=headers, allow_redirects=True, timeout=30) as response:
                        if response.status == 200:
                            cookie_manager.mark_cookie_success(new_cookies)
                            image_data = await response.read()
                            
                            # Response header'larını ayarla
                            response_headers = {
                                'Content-Type': response.headers.get('content-type', 'image/jpeg'),
                                'Cache-Control': 'public, max-age=31536000',
                                'Access-Control-Allow-Origin': '*',
                                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                                'Access-Control-Allow-Headers': '*',
                                'Cross-Origin-Resource-Policy': 'cross-origin',
                                'Cross-Origin-Embedder-Policy': 'require-corp',
                                'Cross-Origin-Opener-Policy': 'same-origin',
                                'Timing-Allow-Origin': '*'
                            }
                            
                            return Response(
                                content=image_data,
                                headers=response_headers,
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
    
    # Eğer resim alınamazsa varsayılan bir resim döndür
    fallback_svg = '''
    <svg width="400" height="500" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#f3f4f6"/>
        <text x="50%" y="50%" font-family="Arial" font-size="20" fill="#9ca3af" text-anchor="middle" dy=".3em">
            Önizleme Yüklenemedi
        </text>
    </svg>
    '''
    
    return Response(
        content=fallback_svg,
        media_type='image/svg+xml',
        headers={
            'Cache-Control': 'no-cache',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Cross-Origin-Resource-Policy': 'cross-origin',
            'Cross-Origin-Embedder-Policy': 'require-corp',
            'Cross-Origin-Opener-Policy': 'same-origin',
            'Timing-Allow-Origin': '*'
        }
    )

@app.get("/api/preview")
async def get_preview(request: Request):
    """Post veya reel önizlemesi al"""
    try:
        url = request.query_params.get('url')
        if not url:
            raise HTTPException(status_code=400, detail='URL is required')

        shortcode = get_shortcode_from_url(url)
        if not shortcode:
            raise HTTPException(status_code=400, detail='Invalid Instagram URL')

        # Story URL'si ise hata döndür
        if shortcode.startswith('story_'):
            raise HTTPException(status_code=400, detail='Stories are not supported for preview')

        max_retries = 10  # Increased max retries
        base_delay = 1  # Reduced base delay
        last_error = None
        used_cookies = set()
        rate_limited_cookies = set()

        for attempt in range(max_retries):
            try:
                # Get a new cookie that hasn't been used or rate limited in this request
                new_cookies = cookie_manager.get_next_cookie()
                
                if not new_cookies:
                    logger.warning(f"No available cookies, waiting {base_delay}s before retry")
                    await asyncio.sleep(base_delay)
                    continue

                cookie_id = new_cookies.get('ds_user_id')
                if cookie_id in used_cookies or cookie_id in rate_limited_cookies:
                    logger.debug(f"Cookie {cookie_id} already used/rate limited in this request, skipping")
                    continue

                used_cookies.add(cookie_id)
                
                loader = await loader_pool.get_loader()
                loader_pool.load_cookies_to_loader(loader, new_cookies)

                # Add small delay between attempts
                if attempt > 0:
                    await asyncio.sleep(base_delay)

                post = instaloader.Post.from_shortcode(loader.context, shortcode)
                
                # Get thumbnail and video URLs safely
                thumbnail_url = None
                video_url = None
                
                try:
                    if post.is_video:
                        thumbnail_url = post.video_thumbnail_url
                        video_url = post.video_url
                    else:
                        thumbnail_url = post.url
                except Exception as e:
                    logger.warning(f"Error getting primary URLs: {str(e)}, trying fallback")
                    try:
                        node = next(iter(post.get_sidecar_nodes()), post)
                        thumbnail_url = node.url
                        if hasattr(node, 'video_url'):
                            video_url = node.video_url
                    except Exception as e2:
                        logger.warning(f"Error getting fallback URLs: {str(e2)}")
                        thumbnail_url = post.url
                
                if not thumbnail_url:
                    raise ValueError("Could not get media URL")
                
                preview_info = {
                    "type": "video" if video_url else "photo",
                    "thumbnail": thumbnail_url,
                    "video_url": video_url,
                    "caption": post.caption if post.caption else "",
                    "likes": post.likes if hasattr(post, 'likes') else 0,
                    "comments": post.comments if hasattr(post, 'comments') else 0,
                    "owner": post.owner_username,
                    "timestamp": post.date.isoformat()
                }

                # Mark cookie as successful
                cookie_manager.mark_cookie_success(new_cookies)
                return preview_info

            except Exception as e:
                error_msg = str(e).lower()
                if new_cookies:
                    if "rate_limit" in error_msg or "please wait" in error_msg:
                        logger.warning(f"Cookie {cookie_id} rate limited, marking and trying next")
                        cookie_manager.mark_cookie_rate_limited(new_cookies)
                        rate_limited_cookies.add(cookie_id)
                        continue  # Skip delay and try next cookie immediately
                    elif "login_required" in error_msg or "checkpoint_required" in error_msg or "unauthorized" in error_msg:
                        logger.warning(f"Cookie {cookie_id} challenged, marking and trying next")
                        cookie_manager.mark_cookie_challenge(new_cookies)
                        continue  # Skip delay and try next cookie immediately
                
                if attempt < max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                    continue
                last_error = str(e)

        # All retries failed
        logger.error(f"All preview attempts failed. Last error: {last_error}")
        raise HTTPException(
            status_code=429,
            detail="All available cookies are rate limited. Please try again later."
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Preview error: {str(e)}")
        if "rate_limit" in str(e).lower() or "please wait" in str(e).lower():
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again later."
            )
        raise HTTPException(status_code=500, detail=str(e))

# Admin şifre güncelleme endpoint'i
@app.post("/api/admin/password")
async def update_password_endpoint(
    request: Request,
    admin: Admin = Depends(get_current_admin_from_token)
):
    """Admin şifresini güncelle"""
    try:
        data = await request.json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')

        if not current_password or not new_password:
            raise HTTPException(status_code=400, detail="Both current and new passwords are required")

        # Mevcut şifreyi doğrula
        if not verify_admin_password(admin, current_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        # Yeni şifreyi güncelle
        if update_admin_password(admin.id, new_password):
            return {"message": "Password updated successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update password")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Update password error: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while updating password")

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """About page route"""
    translations = get_translations('en')  # Default to English
    return templates.TemplateResponse("about.html", {
        "request": request,
        "translations": translations,
        "current_lang": 'en',
        "languages": get_languages()
    })

@app.get("/{lang_code}/about", response_class=HTMLResponse)
async def about_page_with_lang(request: Request, lang_code: str):
    """About page with language code"""
    translations = get_translations(lang_code)
    return templates.TemplateResponse("about.html", {
        "request": request,
        "translations": translations,
        "current_lang": lang_code,
        "languages": get_languages()
    })

@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    """Contact page route"""
    translations = get_translations('en')  # Default to English
    return templates.TemplateResponse("contact.html", {
        "request": request,
        "translations": translations,
        "current_lang": 'en',
        "languages": get_languages()
    })

@app.get("/{lang_code}/contact", response_class=HTMLResponse)
async def contact_page_with_lang(request: Request, lang_code: str):
    """Contact page with language code"""
    translations = get_translations(lang_code)
    return templates.TemplateResponse("contact.html", {
        "request": request,
        "translations": translations,
        "current_lang": lang_code,
        "languages": get_languages()
    })

@app.post("/api/contact")
async def handle_contact(request: Request):
    """Handle contact form submissions"""
    try:
        data = await request.json()
        # Burada form verilerini işleyebilirsiniz (örn: e-posta gönderme)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Privacy policy page without language code"""
    return await privacy_page_with_lang(request, "en")

@app.get("/{lang_code}/privacy", response_class=HTMLResponse)
async def privacy_page_with_lang(request: Request, lang_code: str):
    """Privacy policy page with language code"""
    translations = get_translations(lang_code)
    languages = get_languages()
    return templates.TemplateResponse("privacy.html", {
        "request": request,
        "translations": translations,
        "languages": languages,
        "current_lang": lang_code
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 