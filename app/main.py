from fastapi import FastAPI

app = FastAPI(title="ClickUpMCP")

@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}

@app.get("/api/v1/.well-known/mcp.json")
async def manifest():
    return {
        "mcp_name": "ClickUpMCP",
        "description": "Integrates ClickUp tasks", 
        "version": "0.1.0"
    }

@app.post("/mcp")
async def mcp_handler():
    # Placeholder for MCP call
    return {"status": "not implemented"}
