"""Allow running the Tipping Point app via `python -m tipping_point`."""

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Tipping Point API.")
    parser.add_argument("--reload", action="store_true", help="Reload API source changes during local development.")
    args = parser.parse_args()
    uvicorn.run("tipping_point.app:app", host="0.0.0.0", port=8000, reload=args.reload)
