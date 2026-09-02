from fastapi import FastAPI

from gerenet.api.routers import devices


# uvicorn gerenet.api.main:create_app --factory
def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")
    app.include_router(devices.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
