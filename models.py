from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from datetime import datetime
import bcrypt

Base = declarative_base()

class Language(Base):
    __tablename__ = 'languages'
    
    id = Column(Integer, primary_key=True)
    code = Column(String(2), unique=True, nullable=False)  # en, tr, etc.
    name = Column(String(50), nullable=False)  # English, Turkish
    flag = Column(String(50), nullable=False)  # 🇺🇸, 🇹🇷
    is_active = Column(Boolean, default=True)
    
    translations = relationship("Translation", back_populates="language")

class Translation(Base):
    __tablename__ = 'translations'
    
    id = Column(Integer, primary_key=True)
    language_id = Column(Integer, ForeignKey('languages.id'), nullable=False)
    key = Column(String(100), nullable=False)  # title, description, etc.
    value = Column(String(1000), nullable=False)
    
    language = relationship("Language", back_populates="translations")

class Admin(Base):
    __tablename__ = 'admins'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

# Veritabanı bağlantısı
engine = create_engine('sqlite:///database.db')

# Session factory
Session = sessionmaker(bind=engine)

def init_db():
    """Veritabanını başlat"""
    Base.metadata.create_all(engine)
    
    session = Session()
    try:
        # Eğer admin yoksa ekle
        if not session.query(Admin).first():
            print("Creating default admin user...")
            # Şifreyi hashle
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw("admin123".encode('utf-8'), salt)
            
            admin = Admin(
                username="admin",
                password=hashed.decode('utf-8'),
                is_active=True
            )
            session.add(admin)
            session.commit()  # Önce admin'i commit et
            print("Default admin user created successfully!")
            
        # Eğer dil yoksa ekle
        if not session.query(Language).first():
            # Varsayılan dilleri ekle
            en = Language(code='en', name='English', flag='🇺🇸')
            tr = Language(code='tr', name='Türkçe', flag='🇹🇷')
            
            session.add(en)
            session.add(tr)
            session.flush()  # ID'leri almak için flush
            
            # İngilizce çeviriler
            default_en_translations = {
                'site_name': 'InstaTest',
                'title': 'Instagram Media Downloader Tool',
                'subtitle': 'Download Instagram stories, reels, and posts easily',
                'input_placeholder': 'Insert Instagram link here',
                'paste_button': 'Paste',
                'download_button': 'Download',
                'loading_text': 'Processing...',
                'success_text': 'Download completed!',
                'error_text': 'An error occurred',
                'description': 'A powerful tool to download Instagram content with high quality and complete anonymity.',
                'features_title': 'Tool Features',
                'feature1_title': 'Multi-Format Support',
                'feature1_desc': 'Download stories, reels, posts, and IGTV videos',
                'feature2_title': 'High Quality',
                'feature2_desc': 'Get the highest quality available for your downloads',
                'feature3_title': 'Secure & Anonymous',
                'feature3_desc': 'No login required, completely anonymous downloads',
                'feature4_title': 'Fast Processing',
                'feature4_desc': 'Advanced caching and processing for instant downloads',
                'feature5_title': 'Batch Download',
                'feature5_desc': 'Download multiple stories and posts at once',
                'feature6_title': 'Preview Support',
                'feature6_desc': 'Preview content before downloading',
                'tool_section1_title': 'How It Works',
                'tool_section1_desc': 'Our tool uses advanced algorithms to fetch and process Instagram content while maintaining the highest quality.',
                'tool_section2_title': 'Usage Limits',
                'tool_section2_desc': 'To ensure fair usage, there are some rate limits in place. Please wait a few minutes between bulk downloads.',
                'tool_section3_title': 'Supported Content',
                'tool_section3_desc': 'Currently supports public Instagram stories, reels, posts, and IGTV videos.',
                'footer_about': 'About This Tool',
                'footer_about_text': 'An advanced Instagram media downloader tool that respects privacy and delivers high-quality content.',
                'footer_features': 'Features',
                'footer_api': 'API Access',
                'footer_docs': 'Documentation',
                'footer_status': 'System Status',
                'footer_links': 'Quick Links',
                'footer_privacy': 'Privacy Policy',
                'footer_terms': 'Terms of Service',
                'footer_contact': 'Contact',
                'footer_copyright': '© 2024 InstaTest. All rights reserved.',
                'footer_disclaimer': 'This tool is not affiliated with Instagram.',
                # SEO Section
                'seo_title': 'What is Instagram Downloader?',
                'seo_content': '''Instagram Downloader is a powerful online tool designed to help users save and download content from Instagram. As social media becomes increasingly central to our daily lives, the need to save and archive Instagram content has grown significantly. Whether you\'re a content creator, social media manager, or simply someone who wants to keep memorable posts, our Instagram downloader provides a reliable solution.

Our tool supports various types of Instagram content, including photos, videos, stories, and reels. Unlike many other downloaders, we prioritize both quality and user privacy. All downloads maintain the original content quality, ensuring you get the best possible version of the media you want to save.

One of the key advantages of using our Instagram downloader is its simplicity. You don\'t need any technical knowledge or additional software - just paste the URL of the content you want to download, and our system handles the rest. This makes it accessible to everyone, from social media professionals to casual Instagram users.

We also understand the importance of privacy and security in today\'s digital age. Our downloader operates without requiring you to log in to your Instagram account, ensuring your personal information remains protected. Additionally, we don\'t store any of your download history or personal data.

Whether you\'re creating a content portfolio, saving inspiration for future projects, or just wanting to keep precious memories, our Instagram downloader provides a fast, reliable, and secure way to save Instagram content.'''
            }
            
            # Türkçe çeviriler
            default_tr_translations = {
                'site_name': 'InstaTest',
                'title': 'Instagram Medya İndirme Aracı',
                'subtitle': 'Instagram hikayelerini, reels ve gönderilerini kolayca indirin',
                'input_placeholder': 'Instagram linkini buraya yapıştırın',
                'paste_button': 'Yapıştır',
                'download_button': 'İndir',
                'loading_text': 'İşleniyor...',
                'success_text': 'İndirme tamamlandı!',
                'error_text': 'Bir hata oluştu',
                'description': 'Instagram içeriklerini yüksek kalitede ve tam gizlilikle indirmenizi sağlayan güçlü bir araç.',
                'features_title': 'Araç Özellikleri',
                'feature1_title': 'Çoklu Format Desteği',
                'feature1_desc': 'Hikayeleri, reels, gönderileri ve IGTV videolarını indirin',
                'feature2_title': 'Yüksek Kalite',
                'feature2_desc': 'İndirmeleriniz için mevcut en yüksek kaliteyi alın',
                'feature3_title': 'Güvenli ve Anonim',
                'feature3_desc': 'Giriş gerektirmez, tamamen anonim indirme',
                'feature4_title': 'Hızlı İşlem',
                'feature4_desc': 'Gelişmiş önbellek ve işleme ile anında indirme',
                'feature5_title': 'Toplu İndirme',
                'feature5_desc': 'Birden fazla hikaye ve gönderiyi aynı anda indirin',
                'feature6_title': 'Önizleme Desteği',
                'feature6_desc': 'İndirmeden önce içeriği önizleyin',
                'tool_section1_title': 'Nasıl Çalışır',
                'tool_section1_desc': 'Aracımız, en yüksek kaliteyi korurken Instagram içeriğini almak ve işlemek için gelişmiş algoritmalar kullanır.',
                'tool_section2_title': 'Kullanım Limitleri',
                'tool_section2_desc': 'Adil kullanımı sağlamak için bazı hız sınırları vardır. Lütfen toplu indirmeler arasında birkaç dakika bekleyin.',
                'tool_section3_title': 'Desteklenen İçerikler',
                'tool_section3_desc': 'Şu anda herkese açık Instagram hikayeleri, reels, gönderiler ve IGTV videolarını destekler.',
                'footer_about': 'Bu Araç Hakkında',
                'footer_about_text': 'Gizliliğe saygı duyan ve yüksek kaliteli içerik sunan gelişmiş bir Instagram medya indirme aracı.',
                'footer_features': 'Özellikler',
                'footer_api': 'API Erişimi',
                'footer_docs': 'Dokümantasyon',
                'footer_status': 'Sistem Durumu',
                'footer_links': 'Hızlı Bağlantılar',
                'footer_privacy': 'Gizlilik Politikası',
                'footer_terms': 'Kullanım Koşulları',
                'footer_contact': 'İletişim',
                'footer_copyright': '© 2024 InstaTest. Tüm hakları saklıdır.',
                'footer_disclaimer': 'Bu araç Instagram ile bağlantılı değildir.',
                # SEO Section
                'seo_title': 'Instagram İndirici Nedir?',
                'seo_content': '''Instagram İndirici, kullanıcıların Instagram\'dan içerik kaydetmesine ve indirmesine yardımcı olmak için tasarlanmış güçlü bir çevrimiçi araçtır. Sosyal medya günlük hayatımızda giderek daha merkezi bir rol oynarken, Instagram içeriklerini kaydetme ve arşivleme ihtiyacı da önemli ölçüde artmıştır. İster bir içerik üreticisi, ister sosyal medya yöneticisi, isterse sadece unutulmaz gönderileri saklamak isteyen biri olun, Instagram indirme aracımız güvenilir bir çözüm sunar.

Aracımız, fotoğraflar, videolar, hikayeler ve reels dahil olmak üzere çeşitli Instagram içerik türlerini destekler. Diğer birçok indiricinin aksine, hem kaliteye hem de kullanıcı gizliliğine öncelik veriyoruz. Tüm indirmeler orijinal içerik kalitesini korur ve kaydetmek istediğiniz medyanın mümkün olan en iyi versiyonunu almanızı sağlar.

Instagram indiricimizin en önemli avantajlarından biri basitliğidir. Herhangi bir teknik bilgiye veya ek yazılıma ihtiyacınız yok - sadece indirmek istediğiniz içeriğin URL\'sini yapıştırın, sistemimiz gerisini halleder. Bu, sosyal medya profesyonellerinden günlük Instagram kullanıcılarına kadar herkes için erişilebilir olmasını sağlar.

Günümüzün dijital çağında gizlilik ve güvenliğin önemini de anlıyoruz. İndiricimiz, Instagram hesabınıza giriş yapmanızı gerektirmeden çalışır ve kişisel bilgilerinizin korunmasını sağlar. Ayrıca, indirme geçmişinizi veya kişisel verilerinizi saklamıyoruz.

İster bir içerik portföyü oluşturuyor, ister gelecekteki projeler için ilham kaynağı arıyor, ister sadece değerli anıları saklamak istiyor olun, Instagram indiricimiz, Instagram içeriğini kaydetmek için hızlı, güvenilir ve güvenli bir yol sunar.'''
            }
            
            # Çevirileri ekle
            for key, value in default_en_translations.items():
                translation = Translation(language_id=en.id, key=key, value=value)
                session.add(translation)
            
            for key, value in default_tr_translations.items():
                translation = Translation(language_id=tr.id, key=key, value=value)
                session.add(translation)
            
            session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def add_language(code: str, name: str, flag: str, is_active: bool = True):
    """Yeni dil ekle"""
    session = Session()
    try:
        # Önce bu dil kodunun var olup olmadığını kontrol et
        existing = session.query(Language).filter_by(code=code).first()
        if existing:
            session.rollback()
            raise Exception(f"Language with code {code} already exists")
            
        # Yeni dil oluştur
        language = Language(code=code, name=name, flag=flag, is_active=is_active)
        session.add(language)
        session.commit()
        
        # Yeni eklenen dili getir
        new_language = session.query(Language).filter_by(code=code).first()
        return new_language
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def add_translation(language_id: int, key: str, value: str):
    """Dil için çeviri ekle"""
    session = Session()
    try:
        translation = Translation(language_id=language_id, key=key, value=value)
        session.add(translation)
        session.commit()
        return translation
    finally:
        session.close()

def get_language(code: str):
    """Dil koduna göre dil bilgisini getir"""
    session = Session()
    try:
        return session.query(Language).filter_by(code=code).first()
    finally:
        session.close()

def get_translations_for_language(language_id: int):
    """Dil ID'sine göre tüm çevirileri getir"""
    session = Session()
    try:
        return session.query(Translation).filter_by(language_id=language_id).all()
    finally:
        session.close()

def update_translation(language_id: int, key: str, value: str):
    """Çeviriyi güncelle, yoksa ekle"""
    session = Session()
    try:
        translation = session.query(Translation).filter_by(
            language_id=language_id, 
            key=key
        ).first()
        
        if translation:
            translation.value = value
        else:
            translation = Translation(language_id=language_id, key=key, value=value)
            session.add(translation)
            
        session.commit()
        return translation
    finally:
        session.close()

def delete_language(code: str):
    """Dili ve ilişkili çevirileri sil"""
    session = Session()
    try:
        language = session.query(Language).filter_by(code=code).first()
        if language:
            session.delete(language)
            session.commit()
            return True
        return False
    finally:
        session.close()

def update_language(code: str, name: str = None, flag: str = None, is_active: bool = None):
    """Dil bilgilerini güncelle"""
    session = Session()
    try:
        language = session.query(Language).filter_by(code=code).first()
        if language:
            if name is not None:
                language.name = name
            if flag is not None:
                language.flag = flag
            if is_active is not None:
                language.is_active = is_active
            session.commit()
            return language
        return None
    finally:
        session.close()

def add_admin(username: str, password: str) -> Admin:
    """Yeni admin ekle"""
    session = Session()
    try:
        # Şifreyi hashle
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        
        admin = Admin(
            username=username, 
            password=hashed.decode('utf-8'),
            is_active=True
        )
        session.add(admin)
        session.commit()
        return admin
    finally:
        session.close()

def get_admin(username: str) -> Admin:
    """Admin bilgilerini getir"""
    session = Session()
    try:
        return session.query(Admin).filter_by(username=username, is_active=True).first()
    finally:
        session.close()

def update_admin_last_login(admin_id: int):
    """Admin son giriş zamanını güncelle"""
    session = Session()
    try:
        admin = session.query(Admin).get(admin_id)
        if admin:
            admin.last_login = datetime.utcnow()
            session.commit()
    finally:
        session.close()

def delete_admin(admin_id: int):
    """Admin sil (soft delete)"""
    session = Session()
    try:
        admin = session.query(Admin).get(admin_id)
        if admin:
            admin.is_active = False
            session.commit()
    finally:
        session.close()

def get_all_admins():
    """Tüm aktif adminleri getir"""
    session = Session()
    try:
        return session.query(Admin).filter_by(is_active=True).all()
    finally:
        session.close()

def update_admin_password(admin_id: int, new_password: str):
    """Admin şifresini güncelle"""
    session = Session()
    try:
        admin = session.query(Admin).get(admin_id)
        if admin:
            # Şifreyi hashle
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(new_password.encode('utf-8'), salt)
            admin.password = hashed.decode('utf-8')
            session.commit()
            return True
        return False
    finally:
        session.close()

def verify_admin_password(admin: Admin, password: str) -> bool:
    """Admin şifresini doğrula"""
    try:
        stored_hash = admin.password.encode('utf-8')
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash)
    except Exception as e:
        print(f"Password verification error: {str(e)}")
        return False 