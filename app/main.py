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
