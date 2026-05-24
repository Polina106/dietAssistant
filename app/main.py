import logging

from fastapi import FastAPI

from app.api import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Diet Assistant")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
