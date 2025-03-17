# 📸 Instagram Downloader

A powerful and feature-rich Instagram content downloader built with FastAPI and Python.

## 🌟 Features

- 📥 Download Instagram posts, stories, reels, and IGTV videos
- 🔄 Multi-language support
- 🔒 Secure admin panel
- 📊 Download statistics and analytics
- 🔄 Background task processing with Celery
- 💾 Redis caching for improved performance
- 🌐 Proxy support for enhanced reliability
- 📱 Mobile-friendly interface

## 🛠️ Tech Stack

- FastAPI
- Python 3.x
- SQLite
- Redis
- Celery
- Instaloader
- Jinja2 Templates
- Bootstrap

## 📋 Prerequisites

- Python 3.x
- Redis Server
- Instagram account credentials

## 🚀 Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/instagramdownloader.git
cd instagramdownloader
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Initialize the database:
```bash
python -c "from models import init_db; init_db()"
```

## ⚙️ Configuration

Edit the `.env` file with your settings:
```
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
REDIS_URL=redis://localhost:6379
SECRET_KEY=your_secret_key
```

## 🚀 Running the Application

1. Start Redis server:
```bash
redis-server
```

2. Start Celery worker:
```bash
celery -A tasks worker --loglevel=info
```

3. Start the application:
```bash
uvicorn app:app --reload
```

The application will be available at `http://localhost:8000`

## 🔧 Project Structure

```
├── app.py              # Main application file
├── models.py           # Database models
├── tasks.py           # Celery tasks
├── harvester.py       # Instagram content harvester
├── redis_manager.py   # Redis management utilities
├── templates/         # HTML templates
├── static/           # Static files
├── logs/             # Application logs
└── requirements.txt   # Project dependencies
```

NOTE: You need to add more cookies to the project. You should add the cookies to the cookies folder in iterative order like account1.json - account2.json - account3.json.

## 🔒 Security Features

- JWT-based authentication
- Rate limiting
- Input validation
- Secure password handling
- Session management

## 📊 Monitoring

- Download statistics
- Error logging
- Performance metrics
- User activity tracking

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

This tool is for educational purposes only. Please respect Instagram's terms of service and rate limits when using this application.

## 🙏 Acknowledgments

- FastAPI team for the amazing framework
- Instaloader contributors
- All future contributors to this project
