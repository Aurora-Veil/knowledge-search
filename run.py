import uvicorn

from app.config import WEB_WORKERS

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000,
                reload=WEB_WORKERS == 1, workers=WEB_WORKERS)
