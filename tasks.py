from celery import Celery
import requests
import json
import re
import os
from bs4 import BeautifulSoup
import instaloader
from typing import Optional, Dict, Any

# Celery instance
celery = Celery('tasks', broker='pyamqp://guest@localhost//')

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