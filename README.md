# AI Job Listing SaaS - Production-Grade Job Search Platform

A scalable, production-ready SaaS application that uses LLMs to understand natural language job queries and scrapes job listings from multiple sources asynchronously.

## Overview

This project demonstrates enterprise-grade architecture patterns:
- **AI Orchestration**: LangChain agents parse user queries and make intelligent decisions about which scraping tools to invoke
- **Async Processing**: Celery workers handle long-running scraping jobs without blocking user requests
- **Scalable Architecture**: Designed to handle thousands of concurrent users
- **Clean Separation of Concerns**: Views, services, agents, and tasks are cleanly decoupled

## Architecture

![System Architecture](docs/architecture.png)

```
                        ┌─────────────┐
                        │   Browser   │
                        └──────┬──────┘
                               │ HTTP
                               ▼
                        ┌─────────────────────────────┐
                        │   Django Web (Gunicorn)     │
                        ├─────────────────────────────┤
                        │ Views (REST API endpoints)  │
                        │   ├─ POST /api/jobs/submit/ │
                        │   ├─ GET /api/jobs/status/  │
                        │   └─ GET /api/jobs/listing/ │
                        └──────┬──────────────────────┘
                               │ Task Submission
                               ▼
                        ┌─────────────────────────────┐
                        │   Redis Message Broker      │
                        │   (Celery Task Queue)       │
                        └──────┬──────────────────────┘
                               │ Task Consumption
                               ▼
                        ┌──────────────────────────────────────────────┐
                        │         Celery Worker Pool                   │
                        ├──────────────────────────────────────────────┤
                        │ 1. execute_job_search_agent                  │
                        │    └─ LangChain Agent parses user query      │
                        │       └─ Calls Bright Data scraping tools    │
                        │       └─ Creates Snapshot records            │
                        │                                              │
                        │ 2. poll_snapshot_status (recurring)          │
                        │    └─ Checks if Bright Data job is ready     │
                        │    └─ Updates Snapshot.ready flag            │
                        │                                              │
                        │ 3. fetch_and_process_snapshot                │
                        │    └─ Downloads job listings from Bright     │
                        │    └─ Parses and creates JobListing objects  │
                        │                                              │
                        │ 4. summarize_job_listings                    │
                        │    └─ Uses LLM to generate job summaries     │
                        │    └─ Updates LLMResult.status = ready       │
                        └──────────────────────────────────────────────┘
                              │ Data Storage
                              ▼
                        ┌─────────────────────────────┐
                        │   PostgreSQL Database       │
                        ├─────────────────────────────┤
                        │ ├─ LLMResult (user query)   │
                        │ ├─ Snapshot (scrape job)    │
                        │ └─ JobListing (results)     │
                        └─────────────────────────────┘

                        External APIs:
                        ├─ Bright Data (job scraping)
                        ├─ OpenAI (LLM orchestration & summarization)
                        └─ Celery Beat (periodic cleanup tasks)
```

## Data Models

### LLMResult
Represents a single user job search query. The top-level entity.
- `user`: FK to Django User
- `prompt`: The user's natural language query
- `status`: pending → processing → ready (or failed)
- `extracted_params`: Parsed parameters from user query
- `created_at`: Timestamp

### Snapshot
Tracks a single Bright Data scraping job. One LLMResult can have multiple Snapshots (LinkedIn + Glassdoor).
- `llm_result`: FK to LLMResult
- `source`: 'linkedin' or 'glassdoor'
- `snapshot_id`: Unique ID from Bright Data API
- `ready`: Boolean flag
- `raw_data`: Raw JSON response from Bright Data
- `created_at`: Timestamp

### JobListing
A parsed job listing extracted from Snapshot data.
- `llm_result`: FK to LLMResult
- `snapshot`: FK to Snapshot (for audit trail)
- `title`, `company`, `location`: Job metadata
- `url`: Direct link to job posting
- `salary`: Salary range if available
- `description`: Full job description HTML/text
- `summary`: LLM-generated summary
- `relevance_score`: 0.0-1.0 relevance to user query
- `created_at`: Timestamp

## System Flow

1. **User Submits Query** (blocking, returns immediately)
   - Browser sends `POST /api/jobs/submit/` with query text
   - Django creates LLMResult with status="pending"
   - Task `execute_job_search_agent` is queued
   - Response: `{llm_result_id: 123, status: pending}`

2. **Agent Executes** (async Celery worker)
   - LangChain agent parses user query
   - Extracts: role, location, remote, seniority, etc.
   - Calls `search_linkedin_jobs()` tool
   - Calls `search_glassdoor_jobs()` tool
   - Both tools submit to Bright Data API
   - Bright Data returns snapshot IDs immediately
   - Snapshot records created in DB
   - Status updated to "processing"

3. **Polling Phase** (Celery recurring tasks)
   - `poll_snapshot_status` checks each Snapshot
   - Bright Data API returns status: processing/ready/failed
   - When ready, task triggers `fetch_and_process_snapshot`

4. **Data Processing** (Celery worker)
   - Fetches JSON results from Bright Data
   - Parses job listings based on source
   - Creates JobListing objects
   - Triggers `summarize_job_listings` task

5. **Summarization** (Celery worker)
   - LLM summarizes each job description
   - Stores summary in JobListing
   - When all done, LLMResult.status = "ready"

6. **Frontend Poll Completes** (browser polls status endpoint)
   - Browser detects status="ready"
   - Fetches and displays job listings

## Project Structure

```
ai_job_saas/
├── config/                    # Django project settings
│   ├── __init__.py           # Celery app initialization
│   ├── settings.py           # Django configuration
│   ├── urls.py               # Root URL routing
│   ├── wsgi.py               # WSGI entry point
│   └── celery.py             # Celery configuration
├── accounts/                 # User authentication
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   └── urls.py
├── jobs/                     # Job search and scraping
│   ├── models.py             # LLMResult, Snapshot, JobListing
│   ├── views.py              # REST API endpoints
│   ├── services.py           # Bright Data integration
│   ├── agents.py             # LangChain agent
│   ├── tasks.py              # Celery async tasks
│   └── urls.py
├── templates/
│   └── jobs/
│       ├── search.html       # Job search form
│       └── results.html      # Results display
├── docker-compose.yml        # Full system orchestration
├── Dockerfile               # Application container
├── requirements.txt         # Python dependencies
├── .env.example            # Environment template
└── README.md               # This file
```

## Quick Start

### Prerequisites
- Docker & Docker Compose (recommended)
- OR: Python 3.11+, PostgreSQL 15, Redis 7

### Option 1: Docker (Recommended)

```bash
# Clone the repo
git clone <repo>
cd ai_job_saas

# Copy environment template
cp .env.example .env

# Edit .env and add your API keys
nano .env

# Start all services
docker-compose up -d

# Run migrations (in web container)
docker-compose exec web python manage.py migrate

# Create superuser
docker-compose exec web python manage.py createsuperuser

# Visit http://localhost:8000
```

Services will be available at:
- Django Web: http://localhost:8000
- PostgreSQL: localhost:5432
- Redis: localhost:6379
- Admin Panel: http://localhost:8000/admin/

### Option 2: Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set up PostgreSQL
createdb ai_job_saas
createuser -P postgres  # Use password: postgres

# Set up environment
cp .env.example .env
# Edit .env with your local database credentials

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start Redis in separate terminal
redis-server

# Start Django in separate terminal
python manage.py runserver

# Start Celery worker in separate terminal
celery -A config worker -l info

# Start Celery Beat in separate terminal
celery -A config beat -l info
```

## API Endpoints

### Authentication
- `POST /accounts/signup/` - Register new user
- `POST /accounts/login/` - User login
- `POST /accounts/logout/` - User logout

### Job Search
- `POST /api/jobs/submit/` - Submit a job query
  ```json
  {"query": "ML engineer in Paris, remote, fintech"}
  ```
  Returns:
  ```json
  {
    "success": true,
    "llm_result_id": 123,
    "status": "pending"
  }
  ```

- `GET /api/jobs/status/<llm_result_id>/` - Poll for results
  ```json
  {
    "status": "ready",
    "total_jobs": 25,
    "job_listings": [
      {
        "id": 1,
        "title": "Senior ML Engineer",
        "company": "TechCorp",
        "location": "Paris",
        "salary": "€80-120K",
        "url": "https://...",
        "summary": "..."
      }
    ]
  }
  ```

- `GET /api/jobs/listing/<job_id>/` - Get full job details

- `GET /api/jobs/history/` - User's search history

## Configuration

### Environment Variables

Key variables in `.env`:

```bash
# Django
DEBUG=False
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database (PostgreSQL recommended for production)
DB_NAME=ai_job_saas
DB_USER=postgres
DB_PASSWORD=secure_password
DB_HOST=db  # 'db' in Docker, 'localhost' locally

# Redis/Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# External APIs (required)
OPENAI_API_KEY=sk-...
BRIGHT_DATA_API_KEY=...
```

### Celery Configuration

Default settings in `config/settings.py`:
- Task timeout: 30 minutes
- Result expiration: 1 hour
- Broker: Redis
- Serializer: JSON
- Worker concurrency: 4 (via Gunicorn)

Periodic tasks (Celery Beat):
- `cleanup_old_snapshots`: Daily at 2 AM, deletes snapshots older than 7 days

## Deployment

### On Linux/Cloud (e.g., DigitalOcean, AWS, Google Cloud)

```bash
# SSH into server
ssh user@server

# Clone repo and set up
git clone <repo>
cd ai_job_saas
cp .env.example .env
# Edit .env with production secrets

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
bash get-docker.sh

# Run with Compose
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker-compose logs -f web
docker-compose logs -f celery_worker
```

### Production Checklist

- [ ] Set `DEBUG=False` in `.env`
- [ ] Generate strong `SECRET_KEY`
- [ ] Use environment variables for all secrets (API keys)
- [ ] Set up HTTPS/SSL (use nginx reverse proxy + Let's Encrypt)
- [ ] Configure PostgreSQL backups
- [ ] Set up monitoring/alerting (Sentry, DataDog)
- [ ] Enable CSRF protection with proper `ALLOWED_HOSTS`
- [ ] Use connection pooling for PostgreSQL (pgBouncer)
- [ ] Scale Celery workers based on load
- [ ] Monitor Redis memory usage
- [ ] Set up log aggregation (ELK, CloudWatch)

## Monitoring and Debugging

### Check Celery Tasks
```bash
# Inside web container
docker-compose exec web python manage.py shell
>>> from celery.result import AsyncResult
>>> result = AsyncResult('task-id-here')
>>> result.status
>>> result.result
```

### View Task Queue
```bash
# Monitor Redis queue size
docker-compose exec redis redis-cli LLEN celery
```

### Logs
```bash
docker-compose logs web          # Django
docker-compose logs celery_worker # Celery
docker-compose logs redis        # Redis
```

## Performance Considerations

### Scaling the System

1. **More Celery Workers**: Add more worker containers
   ```yaml
   celery_worker_2:
     extends: celery_worker
     # Each worker processes tasks in parallel
   ```

2. **Database Optimization**:
   - Ensure indexes on `snapshot_id`, `llm_result`, `ready`
   - Use connection pooling (pgBouncer)
   - Regular VACUUM and ANALYZE

3. **Redis Optimization**:
   - Use Redis Cluster for horizontal scaling
   - Configure eviction policy
   - Monitor memory usage

4. **API Rate Limiting**:
   ```python
   # Add to views.py
   from rest_framework.throttling import UserRateThrottle
   
   class JobSearchThrottle(UserRateThrottle):
       scope = 'job_search'
       rate = '10/hour'
   ```

### Caching
```python
# Cache repeated queries
from django.views.decorators.cache import cache_page

@cache_page(60 * 5)  # 5 minute cache
def get_search_status(request, llm_result_id):
    ...
```

## Common Issues

### "No module named 'config.celery'"
Ensure `config/__init__.py` contains:
```python
from .celery import app as celery_app
__all__ = ('celery_app',)
```

### Celery tasks not running
- Check Redis is running: `redis-cli ping`
- Check Celery worker logs: `docker-compose logs celery_worker`
- Ensure CELERY_BROKER_URL is correct in `.env`

### Bright Data API timeout
- Increase timeout in `jobs/services.py` BrightDataScraper class
- Check API key is valid
- Monitor API rate limits

### Database connection errors
- Ensure PostgreSQL is running and accessible
- Check DB credentials in `.env`
- Run migrations: `python manage.py migrate`

## Future Enhancements

1. **Ranking System**: Machine learning model to rank job relevance
2. **Semantic Search**: Vector embeddings for better job matching
3. **Caching Layer**: Cache results for repeated queries
4. **User Preferences**: Save search filters and preferences
5. **Email Alerts**: Notify users of new matching jobs
6. **Browser Extension**: Quick job search from any site
7. **Mobile App**: React Native mobile clients
8. **Analytics**: Track popular searches, conversion rates
9. **Multi-language**: Support queries in multiple languages
10. **Advanced Filtering**: Salary range, company size, benefits filtering

## Contributing

Pull requests welcome. Please ensure:
- Code follows PEP 8
- Tests pass: `pytest`
- Type hints where possible
- Docstrings for all functions

## License

MIT