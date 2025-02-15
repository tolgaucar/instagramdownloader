from celery import Celery
import requests
import json
import re
import os
from bs4 import BeautifulSoup
import instaloader
from typing import Optional, Dict, Any
from redis_manager import RedisManager
import logging
import time
from datetime import datetime, timedelta
import aiohttp
import asyncio

# Celery instance
celery = Celery('tasks', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

# Redis bağlantısı
redis_manager = RedisManager()

class InstagramDownloader:
    def __init__(self):
        self.L = instaloader.Instaloader()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }

    def extract_media_url(self, data: Dict[str, Any]) -> Optional[str]:
        """JSON yanıtından medya URL'sini çıkar"""
        try:
            if 'items' in data and len(data['items']) > 0:
                item = data['items'][0]
                
                # Video kontrolü
                if 'video_versions' in item:
                    return item['video_versions'][0]['url']
                
                # Resim kontrolü
                elif 'image_versions2' in item:
                    return item['image_versions2']['candidates'][0]['url']
                
                # Carousel medya kontrolü
                elif 'carousel_media' in item:
                    media_urls = []
                    for carousel_item in item['carousel_media']:
                        if 'video_versions' in carousel_item:
                            media_urls.append(carousel_item['video_versions'][0]['url'])
                        else:
                            media_urls.append(carousel_item['image_versions2']['candidates'][0]['url'])
                    return media_urls[0]  # İlk medyayı döndür
            
            return None
        except Exception as e:
            print(f"Media URL extraction error: {str(e)}")
            return None

    def download_media(self, url: str) -> Dict[str, Any]:
        """Medyayı indir ve kaydet"""
        try:
            # Instagram post ID'sini çıkar
            shortcode = re.search(r'/p/([^/]+)/', url)
            if not shortcode:
                shortcode = re.search(r'/reel/([^/]+)/', url)
            
            if not shortcode:
                return {"success": False, "error": "Invalid Instagram URL"}

            post_code = shortcode.group(1)
            
            # GraphQL endpoint'ini kullan
            post_url = f"https://www.instagram.com/p/{post_code}/?__a=1"
            response = requests.get(post_url, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
                media_url = self.extract_media_url(data)
                
                if media_url:
                    # Medya dosyasını indir
                    media_response = requests.get(media_url, headers=self.headers)
                    if media_response.status_code == 200:
                        # Dosya adını oluştur
                        file_extension = "mp4" if "video" in media_response.headers.get('content-type', '') else "jpg"
                        filename = f"downloads/{post_code}.{file_extension}"
                        
                        # Dizini oluştur
                        os.makedirs("downloads", exist_ok=True)
                        
                        # Dosyayı kaydet
                        with open(filename, 'wb') as f:
                            f.write(media_response.content)
                        
                        return {
                            "success": True,
                            "file_path": filename,
                            "media_type": file_extension
                        }
                
                return {"success": False, "error": "Media URL not found"}
            
            return {"success": False, "error": f"Instagram API error: {response.status_code}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

@celery.task(name='tasks.process_download')
def process_download(url: str, media_type: str = "post") -> Dict[str, Any]:
    """Download task'ini işle"""
    downloader = InstagramDownloader()
    result = downloader.download_media(url)
    return result 

@celery.task
def download_media(url: str, cookie_id: str = None):
    """Medya indirme işlemini arka planda gerçekleştir"""
    try:
        # Cookie bilgisini al
        if cookie_id:
            cookie_key = f"cookie:{cookie_id}"
            cookie_data = redis_manager.get(cookie_key)
            if not cookie_data:
                raise Exception("Cookie not found")
        
        # İndirme işlemini başlat
        start_time = time.time()
        
        # Asenkron indirme işlemini senkron context'te çalıştır
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(download_media_async(url, cookie_data if cookie_id else None))
        
        # İşlem süresini hesapla
        duration = time.time() - start_time
        
        # Başarılı indirme istatistiklerini güncelle
        if cookie_id:
            update_cookie_stats(cookie_id, True, duration)
        
        return result
    except Exception as e:
        logging.error(f"Download failed: {str(e)}")
        if cookie_id:
            update_cookie_stats(cookie_id, False, 0)
        raise

async def download_media_async(url: str, cookie_data: dict = None):
    """Asenkron medya indirme işlemi"""
    async with aiohttp.ClientSession() as session:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        if cookie_data:
            headers['Cookie'] = '; '.join([f"{k}={v}" for k, v in cookie_data.items()])
        
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                raise Exception(f"Download failed with status {response.status}")
            
            content = await response.read()
            return content

def update_cookie_stats(cookie_id: str, success: bool, duration: float):
    """Cookie istatistiklerini güncelle"""
    try:
        stats_key = f"cookie_stats:{cookie_id}"
        current_stats = redis_manager.get(stats_key) or {
            'successes': 0,
            'failures': 0,
            'total_duration': 0,
            'last_success': None,
            'last_failure': None
        }
        
        if success:
            current_stats['successes'] += 1
            current_stats['last_success'] = datetime.utcnow().isoformat()
        else:
            current_stats['failures'] += 1
            current_stats['last_failure'] = datetime.utcnow().isoformat()
        
        current_stats['total_duration'] += duration
        
        # İstatistikleri 24 saat TTL ile kaydet
        redis_manager.set(stats_key, current_stats, ttl=86400)
    except Exception as e:
        logging.error(f"Failed to update cookie stats: {str(e)}")

@celery.task
def cleanup_old_data():
    """Eski verileri temizle"""
    try:
        # Eski cookie istatistiklerini temizle
        redis_manager.cleanup_keys("cookie_stats:*", max_keys=1000)
        
        # Eski task kayıtlarını temizle
        redis_manager.cleanup_keys("task:*", max_keys=1000)
        
        # Eski rate limit kayıtlarını temizle
        redis_manager.cleanup_keys("rate_limit:*", max_keys=1000)
    except Exception as e:
        logging.error(f"Cleanup task failed: {str(e)}")

@celery.task
def monitor_system_health():
    """Sistem sağlığını kontrol et"""
    try:
        import psutil
        
        # Sistem kaynak kullanımını kontrol et
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        health_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'disk_percent': disk.percent,
            'warning_level': 'normal'
        }
        
        # Yüksek kaynak kullanımı varsa uyarı seviyesini güncelle
        if cpu_percent > 80 or memory.percent > 80 or disk.percent > 80:
            health_data['warning_level'] = 'high'
        
        # Sağlık verilerini Redis'e kaydet
        redis_manager.set('system_health', health_data, ttl=300)  # 5 dakika TTL
        
        return health_data
    except Exception as e:
        logging.error(f"Health monitoring failed: {str(e)}")
        return None

# Celery beat schedule tanımlamaları
celery.conf.beat_schedule = {
    'cleanup-old-data': {
        'task': 'tasks.cleanup_old_data',
        'schedule': timedelta(hours=1),
    },
    'monitor-system-health': {
        'task': 'tasks.monitor_system_health',
        'schedule': timedelta(minutes=5),
    },
}

celery.conf.timezone = 'UTC' 