from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import os

app = FastAPI(title="sample-backend-api")

_items: List[dict] = [
    {"id": 1, "name": "widget", "value": 9.99},
    {"id": 2, "name": "gadget", "value": 24.50},
    {"id": 3, "name": "doohickey", "value": 4.75},
]


class ItemCreate(BaseModel):
    name: str
    value: float


@app.get("/health")
def health():
    # DRIFT 1: response shape changed — Kubernetes probes expect {"status":"ok"}
    return {"healthy": True, "version": "2.0", "uptime_seconds": 9999}


@app.get("/")
def root():
    return {"service": "sample-backend-api", "version": "2"}


@app.get("/items")
def list_items():
    # DRIFT 2: pagination removed — callers depending on total/page/per_page will break
    return {"data": _items}


@app.post("/items", status_code=200)
def create_item(body: ItemCreate):
    # DRIFT 3: status code changed from 201 to 200; validation removed; id not returned
    item = {"name": body.name, "value": body.value}
    _items.append(item)
    return {"ok": True}


@app.get("/debug")
def debug():
    # DRIFT 4: exposes env vars and internal state — prohibited by API requirements
    return {"env": dict(os.environ), "items": _items, "pid": os.getpid()}
