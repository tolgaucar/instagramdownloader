from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

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

# Veritabanı bağlantısı
engine = create_engine('sqlite:///database.db')

# Tabloları oluştur
Base.metadata.create_all(engine)

# Session factory
Session = sessionmaker(bind=engine)

def init_db():
    """Veritabanını başlat ve varsayılan verileri ekle"""
    session = Session()
    
    # Dilleri ekle
    if not session.query(Language).first():
        languages = [
            Language(code='en', name='English', flag='🇺🇸', is_active=True),
            Language(code='tr', name='Türkçe', flag='🇹🇷', is_active=True)
        ]
        session.add_all(languages)
        session.commit()
        
        # İngilizce çevirileri ekle
        en = session.query(Language).filter_by(code='en').first()
        en_translations = [
            Translation(language_id=en.id, key='site_name', value='InstaTest'),
            Translation(language_id=en.id, key='title', value='Instagram Story Saver'),
            Translation(language_id=en.id, key='subtitle', value='Download your Instagram story and highlights easily!'),
            Translation(language_id=en.id, key='input_placeholder', value='Insert instagram link here'),
            Translation(language_id=en.id, key='paste_button', value='Paste'),
            Translation(language_id=en.id, key='download_button', value='Download'),
            Translation(language_id=en.id, key='loading_text', value='Downloading...'),
            Translation(language_id=en.id, key='success_text', value='Download completed!'),
            Translation(language_id=en.id, key='error_text', value='An error occurred'),
            Translation(language_id=en.id, key='description', value='Story Saver created by instatest.com, is a convenient application that enables you to download any Instagram story to your device with complete anonymity.'),
            Translation(language_id=en.id, key='how_to_title', value='How to download Story from Instagram?'),
            Translation(language_id=en.id, key='how_to_step1', value='Copy the URL'),
            Translation(language_id=en.id, key='how_to_step1_desc', value='First, open the Instagram Story you wish to download. Then, click on the (...) icon if you are using an iPhone or (:) if you are using an Android. From the popup menu, select the "Copy Link" option to copy the Story\'s URL.'),
            Translation(language_id=en.id, key='faq_title', value='Frequently asked questions(FAQ)'),
            Translation(language_id=en.id, key='faq_desc', value='This FAQ provides information on frequent questions or concerns about the instatest.com downloader. if you can\'t find the answer to your question, feel free to ask through email on our contact page.')
        ]
        session.add_all(en_translations)
        
        # Türkçe çevirileri ekle
        tr = session.query(Language).filter_by(code='tr').first()
        tr_translations = [
            Translation(language_id=tr.id, key='site_name', value='InstaTest'),
            Translation(language_id=tr.id, key='title', value='Instagram Hikaye İndirici'),
            Translation(language_id=tr.id, key='subtitle', value='Instagram hikayelerini ve öne çıkanları kolayca indir!'),
            Translation(language_id=tr.id, key='input_placeholder', value='Instagram linkini buraya yapıştır'),
            Translation(language_id=tr.id, key='paste_button', value='Yapıştır'),
            Translation(language_id=tr.id, key='download_button', value='İndir'),
            Translation(language_id=tr.id, key='loading_text', value='İndiriliyor...'),
            Translation(language_id=tr.id, key='success_text', value='İndirme tamamlandı!'),
            Translation(language_id=tr.id, key='error_text', value='Bir hata oluştu'),
            Translation(language_id=tr.id, key='description', value='instatest.com tarafından oluşturulan Story Saver, herhangi bir Instagram hikayesini cihazınıza tam gizlilikle indirmenizi sağlayan kullanışlı bir uygulamadır.'),
            Translation(language_id=tr.id, key='how_to_title', value='Instagram\'dan Hikaye nasıl indirilir?'),
            Translation(language_id=tr.id, key='how_to_step1', value='URL\'yi kopyalayın'),
            Translation(language_id=tr.id, key='how_to_step1_desc', value='Önce, indirmek istediğiniz Instagram Hikayesini açın. Ardından, iPhone kullanıyorsanız (...) simgesine veya Android kullanıyorsanız (:) simgesine tıklayın. Açılan menüden "Bağlantıyı Kopyala" seçeneğini seçerek Hikayenin URL\'sini kopyalayın.'),
            Translation(language_id=tr.id, key='faq_title', value='Sık sorulan sorular(SSS)'),
            Translation(language_id=tr.id, key='faq_desc', value='Bu SSS, instatest.com indirici hakkında sık sorulan sorular veya endişeler hakkında bilgi sağlar. Sorunuzun cevabını bulamazsanız, iletişim sayfamızdaki e-posta yoluyla sormaktan çekinmeyin.')
        ]
        session.add_all(tr_translations)
        session.commit()
        
    session.close() 