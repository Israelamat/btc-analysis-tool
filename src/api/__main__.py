import os
import uvicorn
from src.api.app import DEFAULT_HOST, DEFAULT_PORT

def main() -> None:
    """Start the API with uvicorn using the API_HOST / API_PORT env vars."""
    host = os.getenv("API_HOST", DEFAULT_HOST)
    port = int(os.getenv("API_PORT", DEFAULT_PORT))
    reload = os.getenv("API_RELOAD", "0").lower() in ("1", "true", "yes")

    print(f"API listening on http://{host}:{port} (docs: /docs)")
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
