# Zulip Server Analytics API

A lightweight REST API built with **FastAPI** and **Python** for retrieving analytics and user information from an existing **Zulip Server** database.

The API uses asynchronous database access through **SQLAlchemy + asyncpg**, authenticates requests with **JWT Bearer tokens**, protects the token endpoint with **rate limiting**, and reads data directly from Zulip's PostgreSQL tables.

> **Note:** This README documents the API based on the current `main.py` implementation. Configuration details that are not present in the source code are intentionally left as recommendations rather than presented as existing features.

## Features

- JWT-based authentication
- Master API key exchange for access tokens
- 8-hour JWT expiration
- Rate limiting on the authentication endpoint
- Asynchronous PostgreSQL access
- Automatic reflection of selected Zulip database tables at startup
- Server-wide analytics
- Per-realm analytics
- Realm user listing
- Server realm listing
- CORS middleware
- Automatic interactive API documentation through FastAPI

## Architecture

The application connects directly to an existing Zulip PostgreSQL database and reflects these tables during startup:

- `zerver_realm`
- `zerver_userprofile`
- `zerver_message`
- `zerver_client`

The API then exposes a small read-only layer over this data.

```text
Client
  |
  | POST /token
  | API key
  v
FastAPI
  |
  | JWT Bearer token
  v
Protected endpoints
  |
  v
SQLAlchemy AsyncSession
  |
  v
Zulip PostgreSQL Database
```

## Requirements

Recommended environment:

- Python 3.10+
- FastAPI
- Uvicorn
- SQLAlchemy
- asyncpg
- PyJWT
- bcrypt
- python-dotenv
- slowapi
- PostgreSQL
- An accessible Zulip database

## Installation

Clone the repository and create a virtual environment:

```bash
git clone <your-repository-url>
cd <your-repository-directory>

python -m venv .venv
source .venv/bin/activate
```

On Windows:

```powershell
.venv\Scripts\activate
```

Install the required packages:

```bash
pip install fastapi uvicorn sqlalchemy asyncpg pyjwt bcrypt python-dotenv slowapi
```

## Configuration

The application reads configuration values from environment variables using `python-dotenv`.

Create a `.env` file:

```env
DB_USER=your_database_user
DB_HOST=your_database_host
DB_PORT=5432
DB_NAME=your_database_name

JWT_SECRET=your_long_random_secret
ADMIN_API_KEY=your_master_api_key
```

### Environment variables

| Variable | Description |
|---|---|
| `DB_USER` | PostgreSQL username |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port |
| `DB_NAME` | PostgreSQL database name |
| `JWT_SECRET` | Secret used to sign JWT tokens |
| `ADMIN_API_KEY` | Master API key required to obtain a JWT |

### Database connection

The current implementation uses an asynchronous PostgreSQL connection through `asyncpg`.

It is configured to connect through:

```text
/var/run/postgresql/.s.PGSQL.5432
```

This means the current configuration expects a PostgreSQL Unix socket at that location. If the API is deployed separately from the PostgreSQL server, the connection configuration should be adapted accordingly.

## Running the API

Start the application with Uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

For development with automatic reload:

```bash
uvicorn main:app --reload
```

Once running, FastAPI provides interactive documentation at:

```text
http://localhost:8000/docs
```

Alternative ReDoc documentation:

```text
http://localhost:8000/redoc
```

OpenAPI schema:

```text
http://localhost:8000/openapi.json
```

## Authentication

All endpoints except `POST /token` require a valid JWT Bearer token.

### 1. Generate an access token

**Endpoint**

```http
POST /token
```

**Rate limit**

```text
5 requests per minute
```

**Request body**

```json
{
  "api_key": "your_master_api_key"
}
```

**Successful response**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in_hours": 8
}
```

The token contains:

- `sub`: `admin_reporter`
- `exp`: expiration timestamp

### 2. Authenticate protected requests

Send the returned token using the standard Authorization header:

```http
Authorization: Bearer <access_token>
```

Example:

```bash
curl -H "Authorization: Bearer <access_token>" \
  http://localhost:8000/server_realms
```

### Authentication errors

An invalid or expired token returns HTTP `401 Unauthorized`.

An incorrect master API key returns HTTP `403 Forbidden`.

## API Endpoints

### `POST /token`

Generates a JWT access token using the configured administrator API key.

**Authentication:** None

**Request:**

```json
{
  "api_key": "your_master_api_key"
}
```

**Response:**

```json
{
  "access_token": "string",
  "token_type": "bearer",
  "expires_in_hours": 8
}
```

---

### `GET /server_realms`

Returns the realms configured on the Zulip server.

**Authentication:** JWT Bearer token required.

**Response:**

```json
{
  "data": [
    {
      "name": "Example Organization",
      "string_id": "example"
    }
  ]
}
```

The endpoint reads the realm `name` and `string_id` from `zerver_realm`.

---

### `GET /server_analytics`

Returns aggregated statistics for the entire Zulip server.

**Authentication:** JWT Bearer token required.

**Response:**

```json
{
  "data": {
    "total_realms": 1,
    "total_users": 50,
    "total_messages": 12000,
    "active_users_15_days": 32,
    "messages_15_days": 2500,
    "clients_count_connection": {
      "ZulipMobile": 1500,
      "ZulipDesktop": 500
    }
  }
}
```

### Returned metrics

| Field | Description |
|---|---|
| `total_realms` | Total number of realms |
| `total_users` | Total number of users |
| `total_messages` | Total number of messages |
| `active_users_15_days` | Users whose `last_login` occurred within the last 15 days |
| `messages_15_days` | Messages sent within the last 15 days |
| `clients_count_connection` | Message count grouped by sending client |

The 15-day analytics window is calculated dynamically from the current UTC time.

---

### `GET /realm_analytics/{string_id}`

Returns analytics for a specific Zulip realm.

**Authentication:** JWT Bearer token required.

**Path parameter:**

| Parameter | Description |
|---|---|
| `string_id` | Zulip realm string identifier |

Example:

```http
GET /realm_analytics/example
```

**Response:**

```json
{
  "data": {
    "total_realms": 1,
    "total_users": 25,
    "total_messages": 6000,
    "active_users_15_days": 18,
    "messages_15_days": 1300,
    "clients_count_connection": {
      "ZulipMobile": 800,
      "ZulipDesktop": 300
    }
  }
}
```

The endpoint applies the same 15-day activity window used by `/server_analytics`, but scopes the user and message statistics to the requested realm.

---

### `GET /users_by_realm/{string_id}`

Returns users belonging to a specific Zulip realm.

**Authentication:** JWT Bearer token required.

**Path parameter:**

| Parameter | Description |
|---|---|
| `string_id` | Zulip realm identifier |

Example:

```http
GET /users_by_realm/example
```

**Response:**

```json
{
  "data": [
    {
      "full_name": "John Doe",
      "email": "john@example.com",
      "delivery_email": "john@example.com",
      "active": true
    }
  ]
}
```

The endpoint returns:

- Full name
- Email
- Delivery email
- Active status

## Example workflow

### Step 1 — Request a token

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/json" \
  -d '{"api_key":"your_master_api_key"}'
```

Copy the `access_token` from the response.

### Step 2 — Request server realms

```bash
curl http://localhost:8000/server_realms \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Step 3 — Request server analytics

```bash
curl http://localhost:8000/server_analytics \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Step 4 — Request realm analytics

```bash
curl http://localhost:8000/realm_analytics/example \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Step 5 — List realm users

```bash
curl http://localhost:8000/users_by_realm/example \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Security

The API implements several security mechanisms:

### JWT authentication

Protected endpoints require a JWT signed using the configured `JWT_SECRET`.

### Token expiration

Access tokens expire after **8 hours**.

### Master API key

The `/token` endpoint requires the configured `ADMIN_API_KEY`.

### Rate limiting

The token endpoint is limited to:

```text
5 requests / minute
```

### CORS

The current implementation allows all origins:

```python
allow_origins=["*"]
```

For production deployments, this should ideally be restricted to the trusted frontend origin(s).

## Database considerations

This API does not create or migrate the Zulip database schema. Instead, it reflects existing tables at application startup.

The current implementation expects the following Zulip tables to exist:

```text
zerver_realm
zerver_userprofile
zerver_message
zerver_client
```

The application performs read operations against these tables.

Because the API is coupled to Zulip's database schema, major Zulip upgrades may require reviewing the queries and table structure used by the API.

## Project structure

A minimal deployment can use:

```text
.
├── main.py
├── .env
├── .gitignore
└── README.md
```

A production project could later be organized into:

```text
.
├── app/
│   ├── main.py
│   ├── auth/
│   ├── database/
│   ├── models/
│   └── routes/
├── .env
├── .gitignore
├── requirements.txt
└── README.md
```

## Production recommendations

Before exposing the API publicly, consider:

- Restricting CORS to known frontend domains.
- Storing `.env` outside version control.
- Using a strong, randomly generated `JWT_SECRET`.
- Rotating the administrator API key periodically.
- Running behind HTTPS.
- Running behind a reverse proxy such as Nginx.
- Using a dedicated PostgreSQL user with only the permissions required by the API.
- Pinning Python dependencies in `requirements.txt`.
- Adding structured application logging.
- Adding endpoint-level response models with Pydantic.
- Adding explicit error handling for unknown realms.
- Monitoring database connection health.
- Reviewing compatibility whenever the Zulip version is upgraded.

## API Documentation

Because the application is built with FastAPI, interactive documentation is generated automatically.

When the server is running:

- `/docs` — Swagger UI
- `/redoc` — ReDoc
- `/openapi.json` — OpenAPI specification

## License

Add the license that applies to your project here.

## Author

Developed as a FastAPI-based analytics interface for Zulip Server data.
