import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.consumer import start_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


logger = logging.getLogger(__name__)


class _ExpoNoiseFilter(logging.Filter):
    _SKIP = (
        "/inspector/", "/message?role=",
        "connection rejected", "connection closed",
        "Unsupported upgrade request",
        "No supported WebSocket library",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SKIP)


logging.getLogger("uvicorn.access").addFilter(_ExpoNoiseFilter())
logging.getLogger("uvicorn.error").addFilter(_ExpoNoiseFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=start_consumer, daemon=True, name="kafka-consumer")
    thread.start()
    logger.info("Kafka consumer thread started")
    yield
    logger.info("Shutting down")


app = FastAPI(title="Diet Assistant", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}
