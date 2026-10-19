# ClickUpMCP

Twynity-compatible FastMCP server that integrates ClickUp tasks, spaces, lists, and updates.

## Overview

ClickUpMCP is an MCP (Model Context Protocol) server that connects AI agents to ClickUp project management. It provides:

- **OAuth2 Authentication**: Full OAuth2 login flow with ClickUp for user access
- **Token-based Authentication**: Secure access via ClickUp Personal Access Tokens (PAT)
- **Task Management**: List and create tasks in ClickUp workspaces
- **Encrypted Storage**: API tokens and OAuth refresh tokens stored encrypted in MongoDB, scoped to persona
- **REST API**: Full REST endpoints for token management, project connections, and tool invocation
- **Web UI**: Minimal interface for selecting workspaces, lists, and managing tasks

## Architecture

```
+-----------+     API Token     +----------+
|  User     | ----------------> | ClickUp  |
+-----------+                   +----------+
         |                            ^
         v                            |
    +----------+        API v2        +-----------+
    | ClickUp  | <-------------------> | MCP Tools |
    | Client   |                       +-----------+
    +----------+                             |
         |                                  v
         +------------------> +----------------+
                              |  MongoDB (encrypted tokens)
                              +----------------+
```

## Prerequisites

- Python 3.12+
- MongoDB instance (for storing encrypted API tokens)
- ClickUp Personal Access Token (generate at https://app.clickup.com/api)

## Environment Variables

Create a `.env` file with the following variables:

```bash
# Required: Encryption Key for token storage
# Any string length is accepted; the key is derived via PBKDF2 for Fernet encryption.
# Generate a strong key with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# Example: ClickUpMCP-Default-Encrypt-Key!!
ENCRYPTION_KEY=ClickUpMCP-Default-Encrypt-Key!!

# MongoDB Connection (required for token storage)
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=clickup_mcp
MONGODB_COLLECTION=api_tokens
MONGODB_OAUTH_COLLECTION=oauth_tokens
MONGODB_SESSION_COLLECTION=oauth_sessions

# Optional: ClickUp API Token for direct startup usage
# Tokens are typically provided at runtime via /project/connect
# CLICKUP_API_TOKEN=your_clickup_api_token_here

# OAuth2 Configuration (optional - enables ClickUp OAuth2 login flow)
# CLICKUP_OAUTH_CLIENT_ID=your_clickup_oauth_client_id
# CLICKUP_OAUTH_CLIENT_SECRET=your_clickup_oauth_client_secret
# CLICKUP_OAUTH_REDIRECT_URI=http://your-domain.com/auth/callback

# Server Configuration
HOST=0.0.0.0
PORT=8000

# CORS Configuration (comma-separated origins or * for all)
CORS_ORIGINS=*

# Persona Header (used for multi-tenant scoping)
PERSONA_HEADER=X-Persona-ID
```

## Quick Start

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python -m clickup_mcp

# Or with uvicorn directly
uvicorn clickup_mcp.app:create_app --factory --reload
```

### Docker

```bash
# Build the image
docker build -t clickup-mcp .

# Run the container
docker run -p 8000:8000 --env-file .env clickup-mcp
```

## API Endpoints

### Health & Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check endpoint |
| GET | `/manifest` | MCP server manifest (name, version, capabilities) |
| GET | `/mcp` | MCP protocol info |
| GET | `/mcp/tools` | Available tools with input schemas |

### Authentication (Token-based)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/token/validate?workspace_id=ws-123` | Validate stored token via GET /team |
| POST | `/token/settings` | Save/update encrypted API token |
| DELETE | `/token/settings` | Remove stored token(s) |

### Project Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/project/schema` | Get connection schema and connected workspaces |
| POST | `/project/connect` | Connect workspace with API token |

### Authentication (OAuth2)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/login` | Initiate OAuth2 login flow |
| GET | `/auth/callback` | Handle OAuth2 callback from ClickUp |
| POST | `/auth/logout` | Revoke tokens and disconnect |
| POST | `/auth/refresh` | Refresh expired OAuth2 tokens |

OAuth2 endpoints require the `X-Persona-ID` header for persona scoping.

### Tools

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tools/list_tasks` | List tasks with filters |
| POST | `/tools/create_task` | Create a new task |

All tool endpoints require the `X-Persona-ID` header for persona scoping.

### UI

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ui` | Web-based task management UI |

## MCP Tools

### list_tasks

List tasks in a ClickUp space or list with optional filters.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `list_id` | string | Conditional | ClickUp list ID (required if not using space_id) |
| `space_id` | string | Conditional | ClickUp space ID (required if not using list_id) |
| `workspace_id` | string | No | ClickUp workspace ID (auto-detected if omitted) |
| `status` | string | No | Filter by status name |
| `assignee` | string | No | Filter by assignee ID |
| `priority` | string | No | Filter by priority (1=urgent, 2=high, 3=normal, 4=low) |
| `page_size` | integer | No | Number of results (1-100, default: 25) |
| `include_archived` | boolean | No | Include archived tasks (default: false) |

**Example:**

```bash
curl -X POST http://localhost:8000/tools/list_tasks \
  -H "Content-Type: application/json" \
  -H "X-Persona-ID: user-123" \
  -d '{
    "list_id": "abc123",
    "status": "done",
    "page_size": 10
  }'
```

**Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Found 3 task(s) for workspace=ws-123, list=abc123:\nTask: Q4 Report\n  ID: task-1\n  ..."
    }
  ],
  "structured_content": {
    "workspace_id": "ws-123",
    "filter": "workspace=ws-123, list=abc123",
    "count": 3,
    "tasks": [...],
    "page_size": 10
  }
}
```

### create_task

Create a new task in a specified ClickUp list.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `list_id` | string | Yes | ClickUp list ID |
| `name` | string | Yes | Task name |
| `description` | string | No | Task description |
| `priority` | string | No | Priority (1=urgent, 2=high, 3=normal, 4=low) |
| `status` | string | No | Initial status name |
| `assignee` | string | No | Assignee user ID |
| `due_date` | string | No | Due date (ISO 8601 format) |
| `workspace_id` | string | No | ClickUp workspace ID |

**Example:**

```bash
curl -X POST http://localhost:8000/tools/create_task \
  -H "Content-Type: application/json" \
  -H "X-Persona-ID: user-123" \
  -d '{
    "list_id": "abc123",
    "name": "Review PR #42",
    "description": "Review the authentication PR",
    "priority": "2",
    "due_date": "2025-12-31"
  }'
```

**Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Task created successfully!\n  ID: new-task-1\n  ..."
    }
  ],
  "structured_content": {
    "success": true,
    "task": {...},
    "list_id": "abc123",
    "workspace_id": "ws-123"
  }
}
```

## Usage Tutorial

### Step 1: Start the Server

```bash
# Using the module entry point
python -m clickup_mcp

# Or with environment file
env $(cat .env | xargs) python -m clickup_mcp
```

The server will start on port 8000. The `CLICKUP_API_TOKEN` is **not required** at startup - tokens are provided at runtime via the connection endpoints.

### Step 2: Connect Your ClickUp Workspace

Connect your ClickUp workspace using a Personal Access Token:

```bash
curl -X POST http://localhost:8000/project/connect \
  -H "Content-Type: application/json" \
  -H "X-Persona-ID: user-123" \
  -d '{
    "workspace_id": "ws-123",
    "api_token": "clcu_abc123_secret_token"
  }'
```

The token is encrypted with AES-Fernet and stored in MongoDB, scoped to the persona ID.

You can also use the `/token/settings` endpoint to save tokens:

```bash
curl -X POST http://localhost:8000/token/settings \
  -H "Content-Type: application/json" \
  -H "X-Persona-ID: user-123" \
  -d '{
    "workspace_id": "ws-123",
    "api_token": "clcu_abc123_secret_token"
  }'
```

### Step 3: Validate Your Token

Verify that the stored token is valid by calling the ClickUp `/team` endpoint:

```bash
curl "http://localhost:8000/token/validate?workspace_id=ws-123" \
  -H "X-Persona-ID: user-123"
```

**Response:**

```json
{
  "valid": true,
  "team": {
    "id": "team-123",
    "name": "My Team"
  }
}
```

### Step 4: List Tasks

Use the `/tools/list_tasks` endpoint or the web UI at `/ui` to list tasks:

```bash
curl -X POST http://localhost:8000/tools/list_tasks \
  -H "X-Persona-ID: user-123" \
  -H "Content-Type: application/json" \
  -d '{"list_id": "your-list-id", "page_size": 5}'
```

### Step 5: Create Tasks

Create tasks programmatically:

```bash
curl -X POST http://localhost:8000/tools/create_task \
  -H "X-Persona-ID: user-123" \
  -H "Content-Type: application/json" \
  -d '{
    "list_id": "your-list-id",
    "name": "New Task",
    "priority": "3"
  }'
```

### Step 6: Disconnect

Remove stored tokens:

```bash
# Remove specific workspace
curl -X DELETE http://localhost:8000/token/settings \
  -H "X-Persona-ID: user-123" \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "ws-123"}'

# Remove all workspaces
curl -X DELETE http://localhost:8000/token/settings \
  -H "X-Persona-ID: user-123"
```

### Using the Web UI

Access the web interface at `http://localhost:8000/ui` for a visual interface to:
- Connect workspaces with API tokens
- List tasks with filters
- Create new tasks
- View structured JSON responses

## Project Structure

```
src/
  clickup_mcp/
    __init__.py          # Package init, version
    __main__.py          # Module entry point
    app.py               # FastAPI application with all routes
    config.py            # Settings via pydantic-settings
    crypto.py            # Token encryption (AES-Fernet)
    clickup_client.py    # ClickUp API client (httpx)
    errors.py            # Custom exception classes
    responses.py         # Response helpers
    storage.py           # MongoDB token storage
    tools/
      __init__.py        # Tools package
      base.py            # MCP tool implementations
tests/
  conftest.py            # Shared fixtures
  test_config.py         # Settings tests
  test_crypto.py         # Encryption tests
  test_storage.py        # MongoDB storage tests
  test_tools.py          # MCP tool tests
  test_app.py            # FastAPI endpoint tests
  test_auth.py           # Token authentication tests
  test_clickup_client.py # ClickUp API client tests
Dockerfile               # Multi-stage Docker build
requirements.txt         # Python dependencies
pyproject.toml           # Pytest configuration
```

### OAuth2 Tutorial

1. **Get OAuth2 credentials**: Register an OAuth2 app at https://app.clickup.com/api to get `client_id` and `client_secret`.

2. **Configure OAuth2** in `.env`:
   ```bash
   CLICKUP_OAUTH_CLIENT_ID=your_client_id
   CLICKUP_OAUTH_CLIENT_SECRET=your_client_secret
   CLICKUP_OAUTH_REDIRECT_URI=http://localhost:8000/auth/callback
   ```

3. **Start the server** and visit `/ui` to use the visual OAuth2 login flow, or use the API:
   ```bash
   # Step 1: Get authorization URL
   curl "http://localhost:8000/auth/login?workspace_id=ws-123" \
     -H "X-Persona-ID: user-123"

   # Step 2: Redirect user to the authorization_url returned

   # Step 3: Handle callback at /auth/callback
   # ClickUp redirects to: /auth/callback?code=AUTH_CODE&state=STATE
   ```

4. **Token storage**: Access and refresh tokens are automatically encrypted and stored in MongoDB when the callback succeeds.

5. **Automatic token refresh**: Use `/auth/refresh` to refresh expired OAuth2 tokens before making API calls.

## Deployment Notes

### MongoDB Connection

The MongoDB connection is **lazy** - the server starts immediately without waiting for MongoDB. The connection is established on the first database operation. This prevents startup blocking when MongoDB is temporarily unavailable.

### Encryption Key

The `ENCRYPTION_KEY` is used to encrypt tokens stored in MongoDB. Any string length is accepted — the key is derived via PBKDF2HMAC to produce a Fernet-compatible key. The key is validated at startup with warnings but does not block server initialization.

**Example keys:**
- `ClickUpMCP-Default-Encrypt-Key!!` (32 characters)
- `MySecureKey123` (14 characters)
- Any strong random string

**Generate a secure key:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

This generates a 43-character base64-encoded string that works as the encryption key:

```bash
ENCRYPTION_KEY="aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789_-ab"
```

### Docker Multi-Stage Build

The Dockerfile uses three stages:
1. **Builder**: Install Python dependencies
2. **Test**: Run tests during build (failures are non-fatal)
3. **Runtime**: Minimal production image

```bash
# Build with tests
docker build -t clickup-mcp:latest .

# Run with MongoDB (using a valid 32-byte key)
docker run -p 8000:8000 \
  -e ENCRYPTION_KEY="ClickUpMCP-Default-Encrypt-Key!!" \
  -e MONGODB_URI=mongodb://mongo-host:27017 \
  clickup-mcp:latest
```

## OAuth2 Authentication

ClickUpMCP also supports OAuth2 authentication for user access flows.

### Setup

Configure OAuth2 in your `.env`:

```bash
CLICKUP_OAUTH_CLIENT_ID=your_clickup_oauth_client_id
CLICKUP_OAUTH_CLIENT_SECRET=your_clickup_oauth_client_secret
CLICKUP_OAUTH_REDIRECT_URI=http://your-domain.com/auth/callback
```

### OAuth2 Flow

1. **Login**: Redirect user to ClickUp authorization URL via `/auth/login`
2. **Callback**: Handle the authorization callback at `/auth/callback`
3. **Token Storage**: Access and refresh tokens are encrypted and stored in MongoDB
4. **Logout**: Revoke tokens and remove storage via `/auth/logout`
5. **Refresh**: Automatically refresh expired tokens via `/auth/refresh`

### OAuth2 Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/login` | Initiate OAuth2 login flow |
| GET | `/auth/callback` | Handle OAuth2 callback from ClickUp |
| POST | `/auth/logout` | Revoke tokens and disconnect |
| POST | `/auth/refresh` | Refresh expired OAuth2 tokens |

## Security

- API tokens are encrypted using AES-Fernet before storage
- OAuth2 refresh tokens are encrypted using AES-Fernet before storage
- Encryption keys are derived per-persona using PBKDF2
- No secrets are logged or exposed in API responses
- All error responses are structured and safe
- Token validation calls the ClickUp `/team` endpoint to verify tokens without storing refresh tokens

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src/clickup_mcp --cov-report=term-missing
```

## License

MIT
