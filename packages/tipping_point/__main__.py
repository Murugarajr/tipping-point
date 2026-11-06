"""Allow running the Tipping Point app via `python -m tipping_point`."""

from tipping_point.app import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
