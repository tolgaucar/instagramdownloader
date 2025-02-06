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

# Session factory
Session = sessionmaker(bind=engine)

def init_db():
    """Veritabanını başlat"""
    Base.metadata.create_all(engine)

def add_language(code: str, name: str, flag: str, is_active: bool = True):
    """Yeni dil ekle"""
    session = Session()
    try:
        language = Language(code=code, name=name, flag=flag, is_active=is_active)
        session.add(language)
        session.commit()
        return language
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