import uvicorn

from clickup_mcp.config import get_settings, validate_settings
from clickup_mcp.app import create_app


def main() -> None:
    settings = get_settings()
    validate_settings(settings)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
