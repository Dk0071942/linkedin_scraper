"""Run the web UI: `uv run python -m mvp.web` (default port 8765)."""

import argparse

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--reload", action="store_true",
                   help="Auto-reload on code changes (dev only)")
    args = p.parse_args()
    print(f"\nLinkedIn Scraper MVP UI: http://{args.host}:{args.port}/\n")
    uvicorn.run(
        "mvp.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
