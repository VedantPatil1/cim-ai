from fastapi import FastAPI

app = FastAPI(title="sample-backend-api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "sample-backend-api", "version": "1"}
