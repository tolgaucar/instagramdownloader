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
                'title': 'Instagram Media Downloader',
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
                'seo_title': 'What is Instagram Downloader?',
                'seo_content': 'Instagram Downloader is a powerful online tool designed to help users save and download content from Instagram...',

                # About page translations
                'about_title': 'About Us',
                'about_subtitle': 'Get to Know Us Better',
                'about_story_title': 'Our Story',
                'about_story_p1': 'Founded in 2024, InstaTest was born from the need to safely and easily download Instagram content.',
                'about_story_p2': 'We aim to provide a high-quality download experience while prioritizing user privacy and data security.',
                'about_story_p3': 'We continue to improve ourselves by serving more users every day.',
                'about_mission_title': 'Our Mission',
                'about_mission_text': 'To provide the ability to download Instagram content at the highest quality, securely and quickly.',
                'about_vision_title': 'Our Vision',
                'about_vision_text': 'To become the world\'s most trusted and preferred platform for social media content downloading.',
                'about_values_title': 'Our Values',
                'about_value1_title': 'User Focus',
                'about_value1_text': 'We always prioritize our users\' needs and privacy.',
                'about_value2_title': 'Continuous Improvement',
                'about_value2_text': 'We provide the best experience by continuously improving our services and technology.',
                'about_value3_title': 'Reliability',
                'about_value3_text': 'We earn our users\' trust by providing secure and uninterrupted service.',
                'about_stats_downloads': 'Downloads',
                'about_stats_users': 'Active Users',
                'about_stats_uptime': 'Uptime',

                # Contact page translations
                'contact_title': 'Contact',
                'contact_subtitle': 'Get in Touch with Us',
                'contact_form_title': 'Send a Message',
                'contact_name': 'Your Name',
                'contact_email': 'Your Email',
                'contact_subject': 'Subject',
                'contact_message': 'Your Message',
                'contact_send': 'Send',
                'contact_success': 'Your message has been sent successfully!',
                'contact_error': 'An error occurred while sending the message.',
                'contact_info_title': 'Contact Information',
                'contact_email_title': 'Email',
                'contact_phone_title': 'Phone',
                'contact_faq_title': 'Frequently Asked Questions',
                'contact_faq1_q': 'How can I download?',
                'contact_faq1_a': 'Just paste the Instagram link into the input field and click the Download button.',
                'contact_faq2_q': 'Is it paid?',
                'contact_faq2_a': 'No, our service is completely free.',
                'contact_faq3_q': 'Do I need an Instagram account?',
                'contact_faq3_a': 'No, you don\'t need an Instagram account to download.',
                'contact_faq4_q': 'Is it safe?',
                'contact_faq4_a': 'Yes, all operations are performed securely and anonymously.',

                # Privacy Policy translations
                'privacy_title': 'Privacy Policy',
                'privacy_subtitle': 'How we handle your data',
                'privacy_intro': 'At InstaTest, we take your privacy seriously. This policy explains how we collect, use, and protect your personal information.',
                'privacy_collection_title': 'Information We Collect',
                'privacy_collection_text': 'We only collect the information necessary to provide our service, such as the Instagram links you submit for downloading. We do not store any personal information or download history.',
                'privacy_usage_title': 'How We Use Your Information',
                'privacy_usage_text': 'The information you provide is used solely for processing your download requests. We do not share your information with third parties or use it for marketing purposes.',
                'privacy_cookies_title': 'Cookies and Tracking',
                'privacy_cookies_text': 'We use essential cookies to ensure the proper functioning of our service. These cookies do not track your activity across other websites.',
                'privacy_security_title': 'Data Security',
                'privacy_security_text': 'We implement industry-standard security measures to protect your information. All downloads are processed through secure connections.',
                'privacy_changes_title': 'Changes to This Policy',
                'privacy_changes_text': 'We may update this privacy policy from time to time. Any changes will be posted on this page with an updated revision date.'
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
                'seo_title': 'Instagram İndirici Nedir?',
                'seo_content': 'Instagram İndirici, kullanıcıların Instagram\'dan içerik kaydetmesine ve indirmesine yardımcı olmak için tasarlanmış güçlü bir çevrimiçi araçtır...',

                # About page translations
                'about_title': 'Hakkımızda',
                'about_subtitle': 'Bizi Daha Yakından Tanıyın',
                'about_story_title': 'Hikayemiz',
                'about_story_p1': '2024 yılında kurulan InstaTest, Instagram içeriklerini güvenli ve kolay bir şekilde indirme ihtiyacından doğdu.',
                'about_story_p2': 'Kullanıcı gizliliğini ve veri güvenliğini ön planda tutarak, yüksek kaliteli indirme deneyimi sunmayı hedefliyoruz.',
                'about_story_p3': 'Her geçen gün daha fazla kullanıcıya hizmet vererek, sürekli kendimizi geliştiriyoruz.',
                'about_mission_title': 'Misyonumuz',
                'about_mission_text': 'Instagram içeriklerini en yüksek kalitede, güvenli ve hızlı bir şekilde indirme imkanı sunmak.',
                'about_vision_title': 'Vizyonumuz',
                'about_vision_text': 'Sosyal medya içerik indirme konusunda dünyanın en güvenilir ve tercih edilen platformu olmak.',
                'about_values_title': 'Değerlerimiz',
                'about_value1_title': 'Kullanıcı Odaklılık',
                'about_value1_text': 'Kullanıcılarımızın ihtiyaçlarını ve gizliliğini her zaman ön planda tutuyoruz.',
                'about_value2_title': 'Sürekli İyileştirme',
                'about_value2_text': 'Hizmetlerimizi ve teknolojimizi sürekli geliştirerek en iyi deneyimi sunuyoruz.',
                'about_value3_title': 'Güvenilirlik',
                'about_value3_text': 'Güvenli ve kesintisiz hizmet sunarak kullanıcılarımızın güvenini kazanıyoruz.',
                'about_stats_downloads': 'İndirme',
                'about_stats_users': 'Aktif Kullanıcı',
                'about_stats_uptime': 'Çalışma Süresi',

                # Contact page translations
                'contact_title': 'İletişim',
                'contact_subtitle': 'Bizimle İletişime Geçin',
                'contact_form_title': 'Mesaj Gönderin',
                'contact_name': 'Adınız',
                'contact_email': 'E-posta Adresiniz',
                'contact_subject': 'Konu',
                'contact_message': 'Mesajınız',
                'contact_send': 'Gönder',
                'contact_success': 'Mesajınız başarıyla gönderildi!',
                'contact_error': 'Mesaj gönderilirken bir hata oluştu.',
                'contact_info_title': 'İletişim Bilgileri',
                'contact_email_title': 'E-posta',
                'contact_phone_title': 'Telefon',
                'contact_faq_title': 'Sık Sorulan Sorular',
                'contact_faq1_q': 'Nasıl indirme yapabilirim?',
                'contact_faq1_a': 'Instagram bağlantısını giriş alanına yapıştırıp İndir butonuna tıklamanız yeterli.',
                'contact_faq2_q': 'Ücretli mi?',
                'contact_faq2_a': 'Hayır, hizmetimiz tamamen ücretsizdir.',
                'contact_faq3_q': 'Instagram hesabı gerekli mi?',
                'contact_faq3_a': 'Hayır, indirme yapmak için Instagram hesabına ihtiyacınız yok.',
                'contact_faq4_q': 'Güvenli mi?',
                'contact_faq4_a': 'Evet, tüm işlemler güvenli ve anonim şekilde gerçekleştirilir.',

                # Privacy Policy translations
                'privacy_title': 'Gizlilik Politikası',
                'privacy_subtitle': 'Verilerinizi nasıl işliyoruz',
                'privacy_intro': 'InstaTest olarak gizliliğinizi ciddiye alıyoruz. Bu politika, kişisel bilgilerinizi nasıl topladığımızı, kullandığımızı ve koruduğumuzu açıklar.',
                'privacy_collection_title': 'Topladığımız Bilgiler',
                'privacy_collection_text': 'Sadece hizmetimizi sağlamak için gerekli olan bilgileri, örneğin indirmek için gönderdiğiniz Instagram bağlantılarını topluyoruz. Kişisel bilgilerinizi veya indirme geçmişinizi saklamıyoruz.',
                'privacy_usage_title': 'Bilgilerinizi Nasıl Kullanıyoruz',
                'privacy_usage_text': 'Sağladığınız bilgiler yalnızca indirme isteklerinizi işlemek için kullanılır. Bilgilerinizi üçüncü taraflarla paylaşmıyor veya pazarlama amaçlı kullanmıyoruz.',
                'privacy_cookies_title': 'Çerezler ve İzleme',
                'privacy_cookies_text': 'Hizmetimizin düzgün çalışmasını sağlamak için gerekli çerezleri kullanıyoruz. Bu çerezler, diğer web sitelerindeki etkinliğinizi takip etmez.',
                'privacy_security_title': 'Veri Güvenliği',
                'privacy_security_text': 'Bilgilerinizi korumak için endüstri standardı güvenlik önlemleri uyguluyoruz. Tüm indirmeler güvenli bağlantılar üzerinden işlenir.',
                'privacy_changes_title': 'Bu Politikadaki Değişiklikler',
                'privacy_changes_text': 'Bu gizlilik politikasını zaman zaman güncelleyebiliriz. Herhangi bir değişiklik, güncellenmiş revizyon tarihi ile birlikte bu sayfada yayınlanacaktır.'
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