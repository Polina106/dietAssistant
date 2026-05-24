import logging
import sys
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import KAFKA_ENABLED
from app.consumer import start_consumer

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_root_handler = logging.StreamHandler(sys.stdout)
_root_handler.setFormatter(logging.Formatter(LOG_FORMAT))

logging.basicConfig(level=logging.INFO, handlers=[_root_handler], force=True)

for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.propagate = True

logger = logging.getLogger(__name__)

app = FastAPI(title="Diet Assistant")


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.on_event("startup")
def _launch_kafka_consumer() -> None:
    if not KAFKA_ENABLED:
        logger.info("KAFKA_ENABLED=false — Kafka consumer will NOT be started")
        return
    thread = threading.Thread(target=start_consumer, name="kafka-consumer", daemon=True)
    thread.start()
    logger.info("Kafka consumer thread started")


@app.get("/health")
def health():
    return {"status": "ok"}
