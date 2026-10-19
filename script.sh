#!/bin/bash
# script.sh - Create branch, commit, push, and create draft PR via GitHub REST API
# Usage: bash script.sh <github_token>

set -e

GITHUB_TOKEN="${1:?Usage: bash script.sh <GITHUB_TOKEN>}"

REPO_OWNER="nanabrownsnr"
REPO_NAME="clickup_mcp"
BRANCH="feature/clickup-mcp"
BASE_BRANCH="autodev/0aaa9fcbf8744f5ba2f5b9a41c916e9d"

echo "=== Step 1: Create branch ==="
git checkout -b "$BRANCH" "$BASE_BRANCH"

echo "=== Step 2: Stage all files ==="
git add -A

echo "=== Step 3: Commit changes ==="
git commit -m "feat: implement ClickUpMCP with OAuth2 authentication and MongoDB storage

- Fix MongoDB index conflict in storage.py (_ensure_index pattern)
- Add README with usage instructions and OAuth2 tutorial
- Full ClickUpMCP implementation with FastMCP tools
- OAuth2 login, callback, logout, refresh endpoints
- Encrypted token storage in MongoDB scoped to persona
- List tasks and create task tools with structured output
- Web UI for workspace/list/task management
- Comprehensive pytest test suite (161 tests)"

echo "=== Step 4: Push branch ==="
git push origin "$BRANCH"

echo "=== Step 5: Create draft PR via GitHub REST API ==="
PR_TITLE="feat: implement ClickUpMCP with OAuth2 authentication"
PR_BODY=$(cat <<'EOF'
## Summary

Implements a Twynity-compatible FastMCP server that integrates ClickUp as an external tool through the ClickUp API.

## Changes

### Bug Fix
- **storage.py**: Fixed MongoDB index name collision by adding `_ensure_index()` method that checks for existing indexes before creating them

### New Features
- **OAuth2 Authentication**: Full OAuth2 flow with login, callback, logout, and refresh endpoints
- **Encrypted Storage**: ClickUp OAuth refresh tokens stored encrypted in MongoDB, scoped to persona
- **FastMCP Tools**: 
  - `list_tasks` - List tasks in a space or list with filters
  - `create_task` - Create a new task in a specified list
- **Web UI**: Minimal UI for selecting workspace, list, and task fields
- **Health/Manifest/MCP endpoints**: As per Twynity contract

### Documentation
- **README.md**: Comprehensive usage instructions and OAuth2 tutorial
- Added OAuth2 section with endpoints and flow documentation

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/manifest` | GET | MCP server manifest |
| `/mcp` | GET | MCP protocol info |
| `/mcp/tools` | GET | Available tools with schemas |
| `/auth/login` | GET | OAuth2 login flow |
| `/auth/callback` | GET | OAuth2 callback handler |
| `/auth/logout` | POST | Revoke tokens and disconnect |
| `/auth/refresh` | POST | Refresh expired tokens |
| `/token/validate` | GET | Validate stored token |
| `/token/settings` | POST/DELETE | Save/remove tokens |
| `/project/schema` | GET | Connection schema |
| `/project/connect` | POST | Connect workspace |
| `/tools/list_tasks` | POST | List tasks |
| `/tools/create_task` | POST | Create task |
| `/ui` | GET | Web UI |

## Testing

All 161 tests pass:
- Configuration tests
- Authentication tests (token + OAuth2)
- Tool input/output tests
- Error case tests
- Crypto/encryption tests
- Storage tests (MongoDB mock)
- ClickUp API client tests

## Docker

Multi-stage Dockerfile with build, test, and runtime stages included.
EOF
)

PR_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/pulls" \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github.v3+json" \
  -H "Content-Type: application/json" \
  -d "$(cat <<EOF
{
  "title": "${PR_TITLE}",
  "body": $(echo "$PR_BODY" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))"),
  "head": "${BRANCH}",
  "base": "${BASE_BRANCH}",
  "draft": true
}
EOF
  )
)

PR_HTTP_CODE=$(echo "$PR_RESPONSE" | tail -1)
PR_JSON=$(echo "$PR_RESPONSE" | head -n -1)

if [ "$PR_HTTP_CODE" = "201" ] || [ "$PR_HTTP_CODE" = "200" ]; then
  PR_URL=$(echo "$PR_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['html_url'])")
  echo "=== Draft PR created successfully ==="
  echo "URL: ${PR_URL}"
else
  echo "=== Failed to create PR (HTTP ${PR_HTTP_CODE}) ==="
  echo "$PR_JSON"
  exit 1
fi

echo "=== Done ==="
