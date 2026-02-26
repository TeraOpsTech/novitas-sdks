"""
SDK Testing App — Simple API to test TeraOps SDK

Run:
    pip install fastapi uvicorn python-dotenv
    pip install git+https://github.com/TeraOpsTech/novitas-sdks.git@working#subdirectory=teraops-logging-sdk
    uvicorn server:app --host 0.0.0.0 --port 9201
"""
import logging
from fastapi import FastAPI
from otel_config import setup_otel

# Setup OTEL + TeraOps SDK
logger_provider = setup_otel()

app = FastAPI(title="SDK Testing App")
logger = logging.getLogger("sdk-testing-app")


@app.get("/")
def root():
    logger.info("Root endpoint called")
    return {"message": "I am an API — we are testing TeraOps SDK"}


@app.get("/api/test")
def test_api():
    logger.info("Test API called", extra={"service": "sdk-testing-app", "action": "test"})
    return {"message": "I am an API — we are doing TeraOps SDK testing", "status": "success"}
