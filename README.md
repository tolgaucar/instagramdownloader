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

```bash
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
REDIS_URL=redis://localhost:6379
SECRET_KEY=your_secret_key
```

## 🍪 Cookie Configuration

Create a `cookies` directory and add your Instagram account cookies in JSON format. Example structure:

```json
{
	"_gat_gtag_UA_175894890_5": "1",
	"_ga": "GA1.3.123456789.1234567890",
	"_gid": "GA1.3.987654321.1234567890",
	"_ga_H30R9PNQFN": "GS1.1.1234567890.1.0.1234567890.0.0.0",
	"SUPPORT_CONTENT": "1234567890123456789-123456789",
	"__Secure-ENID": "25.SE=example_secure_value_here"
}
```

Save this file as `cookies/account1.json`. You can add multiple account cookies by creating additional files like `account2.json`, `account3.json`, etc.

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
├── harvester.py       # Instagram cookie management
├── redis_manager.py   # Redis management utilities
├── templates/         # HTML templates
├── static/           # Static files
├── logs/             # Application logs
├── cookies/          # Instagram account cookies
└── requirements.txt   # Project dependencies
```

## �� Cookie Harvester

The `harvester.py` module is responsible for:

- 🔑 Managing Instagram account cookies
- 🔄 Automatic cookie refresh and validation
- 🎯 Handling multiple Instagram accounts
- 🌐 Proxy rotation for reliable cookie harvesting
- 🔒 Secure cookie storage and management
- 📊 Cookie health monitoring and statistics

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
