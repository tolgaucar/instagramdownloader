from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import json
import os
import time
import random
from datetime import datetime
import logging
import redis
import asyncio
from dotenv import load_dotenv
import sys
import traceback
from pathlib import Path
import base64
import requests
from selenium.webdriver.chrome.options import Options
import certifi
import ssl

class InstagramCookieHarvester:
    def __init__(self):
        self.setup_logging()
        self.setup_redis()
        self.cookies_dir = "cookies"  # cookies/ dizinine kaydet
        os.makedirs(self.cookies_dir, exist_ok=True)
        
        # Proxy listesi
        self.proxies = self.load_proxies()
        self.current_proxy_index = 0
        
        # Başarısız giriş denemelerini takip et
        self.failed_attempts = {}
        
        # Account numaralarını takip et
        self.next_account_number = self.get_next_account_number()
        
        # SSL doğrulama ayarlarını devre dışı bırak
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        # Requests session ayarları
        self.session = requests.Session()
        self.session.verify = False
        # SSL uyarılarını kapat
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        
    def setup_logging(self):
        """Logging konfigürasyonu"""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        
        logging.basicConfig(
            filename=os.path.join(log_dir, 'harvester.log'),
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # Console'a da log bas
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)
        
    def setup_redis(self):
        """Redis bağlantısı kur"""
        try:
            self.redis = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=int(os.getenv('REDIS_DB', 0)),
                password=os.getenv('REDIS_PASSWORD'),
                decode_responses=True
            )
            logging.info("Redis connection established")
        except Exception as e:
            logging.error(f"Redis connection failed: {str(e)}")
            self.redis = None
            
    def load_proxies(self):
        """Proxy listesini yükle ve parse et"""
        try:
            proxies = []
            with open('proxies.txt', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            # IP:PORT formatını parse et
                            parts = line.split(':')
                            if len(parts) == 2:  # Sadece IP:PORT
                                ip, port = parts
                                proxies.append({
                                    'ip': ip.strip(),
                                    'port': port.strip(),
                                    'requires_auth': False
                                })
                            elif len(parts) == 4:  # IP:PORT:USERNAME:PASSWORD
                                ip, port, username, password = parts
                                proxies.append({
                                    'ip': ip.strip(),
                                    'port': port.strip(),
                                    'username': username.strip(),
                                    'password': password.strip(),
                                    'requires_auth': True
                                })
                        except Exception as e:
                            logging.warning(f"Error parsing proxy line: {line}, Error: {str(e)}")
                            continue
            
            if not proxies:
                logging.warning("No valid proxies found in proxies.txt")
            else:
                logging.info(f"Loaded {len(proxies)} proxies")
                # İlk proxy'nin detaylarını göster
                first_proxy = proxies[0]
                logging.info(f"First proxy details - IP: {first_proxy['ip']}, Port: {first_proxy['port']}")
            
            return proxies
            
        except FileNotFoundError:
            logging.warning("proxies.txt not found, running without proxies")
            return []
            
    def check_proxy_health(self, proxy):
        """Proxy'nin sağlık durumunu kontrol et"""
        try:
            proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
            proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
            
            # Test için önce basit bir site dene
            response = self.session.get(
                'http://www.google.com',
                proxies=proxies,
                timeout=10,
                verify=certifi.where()
            )
            
            if response.status_code == 200:
                # Şimdi Instagram'ı dene
                response = self.session.get(
                    'https://www.instagram.com',
                    proxies=proxies,
                    timeout=10,
                    verify=certifi.where()
                )
                return response.status_code == 200
                
            return False
            
        except Exception as e:
            logging.error(f"Proxy health check failed: {str(e)}")
            return False

    def get_next_proxy(self):
        """Sıradaki proxy'yi döndür"""
        if not self.proxies:
            return None
            
        # Sıradaki proxy'ye geç
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        next_proxy = self.proxies[self.current_proxy_index]
        
        logging.info(f"Switching to next proxy: {next_proxy['ip']}:{next_proxy['port']}")
        return next_proxy

    def setup_driver(self, specific_proxy=None):
        """Selenium WebDriver'ı hazırla"""
        options = webdriver.ChromeOptions()
        
        # SSL sertifika hatası için ayarlar
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--ignore-ssl-errors')
        options.add_argument('--allow-insecure-localhost')
        options.add_argument('--disable-web-security')
        options.add_argument('--allow-running-insecure-content')
        options.add_argument('--ignore-urlfetcher-cert-requests')
        options.add_argument('--ignore-certificate-errors-spki-list')
        
        # Temel ayarlar
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--start-maximized')
        
        # User agent
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Proxy ayarları
        if specific_proxy:
            proxy = specific_proxy
        elif self.proxies:
            proxy = self.get_next_proxy()
        else:
            proxy = None
            
        if proxy:
            if proxy.get('requires_auth', False):
                proxy_server = f"http://{proxy['username']}:{proxy['password']}@{proxy['ip']}:{proxy['port']}"
            else:
                proxy_server = f"{proxy['ip']}:{proxy['port']}"
            
            options.add_argument(f'--proxy-server={proxy_server}')
            logging.info(f"Using proxy: {proxy['ip']}:{proxy['port']}")
        
        # Otomasyon belirtilerini gizle
        options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # Ek performans ve stabilite ayarları
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-dev-tools')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--no-first-run')
        
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            
            # JavaScript ile otomasyon belirtilerini gizle
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return driver, proxy
        except Exception as e:
            logging.error(f"Driver setup failed: {str(e)}")
            raise

    def get_next_account_number(self):
        """Bir sonraki account numarasını bul"""
        try:
            existing_files = os.listdir(self.cookies_dir)
            account_numbers = []
            for filename in existing_files:
                if filename.startswith('account') and filename.endswith('.json'):
                    try:
                        number = int(filename.replace('account', '').replace('.json', ''))
                        account_numbers.append(number)
                    except ValueError:
                        continue
            
            if account_numbers:
                return max(account_numbers) + 1
            return 1
            
        except Exception as e:
            logging.error(f"Error getting next account number: {str(e)}")
            return 1

    async def login_instagram(self, username, password):
        """Instagram'a giriş yap ve cookie'leri topla"""
        driver = None
        max_retries = len(self.proxies)
        successful_proxy = None
        required_cookies = {'sessionid', 'ds_user_id', 'csrftoken'}
        
        # SSL doğrulama ayarları
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Requests session ayarları
        self.session.verify = False
        
        for attempt in range(max_retries):
            try:
                if self.failed_attempts.get(username, 0) >= 3:
                    wait_time = 30 * 60
                    logging.warning(f"Too many failed attempts for {username}, waiting {wait_time} seconds")
                    await asyncio.sleep(wait_time)
                    self.failed_attempts[username] = 0
                    
                driver, current_proxy = self.setup_driver()
                
                try:
                    driver.get('https://www.instagram.com/accounts/login/')
                except Exception as e:
                    logging.error(f"Failed to load page with proxy, trying next one. Error: {str(e)}")
                    continue
                
                await asyncio.sleep(random.uniform(3, 5))
                
                # Sayfa yüklenene kadar bekle
                try:
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.NAME, "username"))
                    )
                except TimeoutException:
                    logging.warning(f"Login page load timeout, switching proxy...")
                    continue  # Timeout olursa diğer proxy'ye geç
                
                # Cookie popup'ı kapat (eğer varsa)
                try:
                    cookie_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Allow essential and optional cookies')]")
                    cookie_button.click()
                    await asyncio.sleep(1)
                except:
                    pass
                
                # Login form elementlerini bul ve görünür olduklarından emin ol
                username_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "username"))
                )
                password_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "password"))
                )

                # Input alanlarını temizle
                username_input.clear()
                password_input.clear()
                
                await asyncio.sleep(random.uniform(1, 2))

                # Bilgileri gir (karakterleri tek tek ve random gecikmelerle)
                for char in username:
                    username_input.send_keys(char)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                
                await asyncio.sleep(random.uniform(0.8, 1.5))
                
                for char in password:
                    password_input.send_keys(char)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                
                await asyncio.sleep(random.uniform(1, 2))
                
                # Login butonunu bul ve tıklanabilir olmasını bekle
                login_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
                )

                # JavaScript ile scroll
                driver.execute_script("arguments[0].scrollIntoView(true);", login_button)
                await asyncio.sleep(1)

                # Önce JavaScript ile tıkla
                driver.execute_script("arguments[0].click();", login_button)
                await asyncio.sleep(1)

                # Sonra normal tıklama
                try:
                    login_button.click()
                except:
                    pass

                # Login sonrası daha uzun bekleme
                await asyncio.sleep(random.uniform(8, 10))
                
                # URL ve sayfa içeriği kontrolü
                current_url = driver.current_url
                page_source = driver.page_source.lower()

                # Login formunun hala görünür olup olmadığını kontrol et
                try:
                    login_form = driver.find_element(By.TAG_NAME, "form")
                    if login_form.is_displayed():
                        logging.error(f"Login form still visible after click for {username}")
                        continue  # Diğer proxy ile dene
                except:
                    pass  # Form görünmüyorsa bu iyi bir işaret
                
                if "challenge" in current_url:
                    logging.error(f"Challenge required for {username}")
                    self.failed_attempts[username] = self.failed_attempts.get(username, 0) + 1
                    continue  # Diğer proxy ile dene
                    
                if "login" in current_url:
                    if "incorrect password" in page_source:
                        logging.error(f"Incorrect password for {username}")
                    elif "user not found" in page_source:
                        logging.error(f"User not found: {username}")
                    else:
                        logging.error(f"Login failed for {username} - Unknown reason")
                    self.failed_attempts[username] = self.failed_attempts.get(username, 0) + 1
                    continue  # Diğer proxy ile dene
                    
                if "suspicious_login" in current_url:
                    logging.error(f"Suspicious login detected for {username}")
                    self.failed_attempts[username] = self.failed_attempts.get(username, 0) + 1
                    continue  # Diğer proxy ile dene
                
                # Ana sayfaya git ve cookie'leri kontrol et
                driver.get('https://www.instagram.com/')
                await asyncio.sleep(3)
                
                # Cookie'leri topla
                cookies = driver.get_cookies()
                cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}
                
                # Gerekli cookie'lerin hepsinin olup olmadığını kontrol et
                missing_cookies = required_cookies - set(cookie_dict.keys())
                if missing_cookies:
                    logging.error(f"Missing required cookies for {username}: {missing_cookies}")
                    continue  # Diğer proxy ile dene
                
                if 'sessionid' in cookie_dict:
                    # Dosya adını oluştur
                    filename = f"account{self.next_account_number}.json"
                    filepath = os.path.join(self.cookies_dir, filename)
                    
                    # Cookie'leri kaydet
                    with open(filepath, 'w') as f:
                        json.dump(cookie_dict, f, indent=4)
                    
                    # Redis'e ekle
                    if self.redis:
                        self.redis.hset(
                            f"instagram_cookies:{username}",
                            mapping=cookie_dict
                        )
                    
                    logging.info(f"Successfully harvested cookies for {username} as {filename}")
                    self.failed_attempts[username] = 0
                    successful_proxy = current_proxy
                    
                    # Account numarasını artır
                    self.next_account_number += 1
                    
                    return {
                        'username': username,
                        'created_at': datetime.now().isoformat(),
                        'cookies': cookie_dict,
                        'successful_proxy': current_proxy,
                        'filename': filename
                    }
                else:
                    logging.error(f"No valid session cookie found for {username}")
                    continue  # Diğer proxy ile dene
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"Attempt {attempt + 1} failed for {username}: {str(e)}")
                    continue
                logging.error(f"All attempts failed for {username}: {str(e)}")
                return None
                
            finally:
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    
    def verify_cookie(self, cookie_data):
        """Cookie'nin geçerli olup olmadığını kontrol et"""
        driver = None
        try:
            # Başarılı proxy ile doğrulama yap
            successful_proxy = cookie_data.get('successful_proxy')
            driver, _ = self.setup_driver(specific_proxy=successful_proxy)
            
            driver.get('https://www.instagram.com/')
            
            # Cookie'leri yükle
            for name, value in cookie_data['cookies'].items():
                driver.add_cookie({'name': name, 'value': value})
                
            driver.refresh()
            time.sleep(3)
            
            if 'Login' not in driver.title:
                logging.info(f"Cookie verified for {cookie_data['username']}")
                return True
                
            logging.warning(f"Cookie verification failed for {cookie_data['username']}")
            return False
            
        except Exception as e:
            logging.error(f"Cookie verification error: {str(e)}")
            return False
            
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                    
    async def harvest_cookies(self, accounts):
        """Birden fazla hesaptan cookie topla"""
        valid_cookies = []
        
        for account in accounts:
            try:
                username = account['username']
                password = account['password']
                
                logging.info(f"Attempting to harvest cookies for {username}")
                
                cookie_data = await self.login_instagram(username, password)
                
                if cookie_data and self.verify_cookie(cookie_data):
                    valid_cookies.append(cookie_data)
                    logging.info(f"Successfully verified cookies for {username}")
                else:
                    logging.warning(f"Failed to get valid cookies for {username}")
                    
                # Rate limit önleme için random bekleme
                wait_time = random.randint(30, 60)
                logging.info(f"Waiting {wait_time} seconds before next account...")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logging.error(f"Error processing account {account['username']}: {str(e)}")
                continue
                
        return valid_cookies
        
    def sync_cookies_to_main_app(self):
        """Toplanan cookie'leri ana uygulamaya senkronize et"""
        # Bu metodu kaldır çünkü artık doğrudan cookies/ dizinine kaydediyoruz
        pass

    def parse_account_line(self, line):
        """Yeni format account line'ını parse et"""
        try:
            # Boş satırları atla
            line = line.strip()
            if not line:
                return None
                
            # || ile biten satırları temizle
            if line.endswith('||'):
                line = line[:-2]
                
            # Ana bölümleri ayır
            parts = line.split('|')
            if len(parts) != 4:
                logging.error(f"Invalid line format. Expected 4 parts, got {len(parts)}")
                return None
                
            credentials, user_agent, device_ids, cookies = parts
            
            # Kullanıcı adı ve şifreyi ayır
            try:
                username, password = credentials.split(':')
            except ValueError:
                logging.error(f"Invalid credentials format: {credentials}")
                return None
            
            # Cookie'leri parse et
            cookie_dict = {}
            for cookie in cookies.split(';'):
                cookie = cookie.strip()
                if not cookie:
                    continue
                    
                if '=' in cookie:
                    try:
                        name, value = cookie.split('=', 1)
                        cookie_dict[name.strip()] = value.strip()
                    except Exception as e:
                        logging.warning(f"Error parsing cookie: {cookie}, Error: {str(e)}")
                        continue
            
            account_data = {
                'username': username.strip(),
                'password': password.strip(),
                'user_agent': user_agent.strip(),
                'device_ids': [id.strip() for id in device_ids.split(';') if id.strip()],
                'cookies': cookie_dict
            }
            
            logging.info(f"Successfully parsed account: {username}")
            return account_data
            
        except Exception as e:
            logging.error(f"Error parsing account line: {str(e)}\nLine: {line[:100]}...")
            return None

    def load_accounts(self):
        """Hesap listesini yükle"""
        accounts = []
        try:
            with open('accounts.txt', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        account = self.parse_account_line(line)
                        if account:
                            accounts.append(account)
        
            logging.info(f"Loaded {len(accounts)} accounts with cookies")
            return accounts
        except FileNotFoundError:
            logging.error("accounts.txt not found")
            return []

    async def verify_and_refresh_cookies(self, account_data):
        """Var olan cookie'leri doğrula ve gerekirse yenile"""
        driver = None
        try:
            # Özel user agent ile driver'ı hazırla
            options = webdriver.ChromeOptions()
            options.add_argument(f'--user-agent={account_data["user_agent"]}')
            
            # Diğer ayarlar...
            driver = webdriver.Chrome(options=options)
            
            # Cookie'leri yükle
            driver.get('https://www.instagram.com/')
            for name, value in account_data['cookies'].items():
                driver.add_cookie({'name': name, 'value': value})
            
            # Sayfayı yenile ve kontrol et
            driver.refresh()
            await asyncio.sleep(3)
            
            if 'Login' not in driver.title:
                # Cookie'ler hala geçerli
                cookies = driver.get_cookies()
                cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}
                
                # Cookie dosyasını kaydet
                filename = f"account{self.next_account_number}.json"
                filepath = os.path.join(self.cookies_dir, filename)
                
                with open(filepath, 'w') as f:
                    json.dump(cookie_dict, f, indent=4)
                
                logging.info(f"Verified and saved cookies for {account_data['username']} as {filename}")
                self.next_account_number += 1
                
                return True
                
            return False
            
        except Exception as e:
            logging.error(f"Error verifying cookies: {str(e)}")
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                    
    async def harvest_cookies(self, accounts):
        """Cookie'leri doğrula veya yenile"""
        valid_cookies = []
        
        for account in accounts:
            try:
                logging.info(f"Verifying cookies for {account['username']}")
                
                if await self.verify_and_refresh_cookies(account):
                    valid_cookies.append(account)
                    logging.info(f"Successfully verified cookies for {account['username']}")
                else:
                    # Cookie'ler geçersizse normal login ile dene
                    cookie_data = await self.login_instagram(account['username'], account['password'])
                    if cookie_data:
                        valid_cookies.append(cookie_data)
                    
                # Rate limit önleme için bekle
                await asyncio.sleep(random.randint(10, 20))
                
            except Exception as e:
                logging.error(f"Error processing account {account['username']}: {str(e)}")
                continue
                
        return valid_cookies

def load_accounts():
    """Hesap listesini yükle"""
    try:
        with open('accounts.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("accounts.json not found")
        return []

async def main():
    # Environment variables'ları yükle
    load_dotenv()
    
    # Harvester'ı başlat
    harvester = InstagramCookieHarvester()
    
    # Hesapları yükle
    accounts = harvester.load_accounts()
    
    if not accounts:
        logging.error("No accounts found to harvest cookies")
        return
        
    try:
        # Cookie'leri topla
        cookies = await harvester.harvest_cookies(accounts)
        logging.info(f"Harvested {len(cookies)} valid cookies")
        
        # Ana uygulamaya senkronize et
        harvester.sync_cookies_to_main_app()
        
    except Exception as e:
        logging.error(f"Main process error: {str(e)}\n{traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(main()) 