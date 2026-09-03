from fastapi import FastAPI

from gerenet.api.routers import devices, sites


# uvicorn gerenet.api.main:create_app --factory
def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")
    app.include_router(devices.router)
    app.include_router(devices.snap_router)
    app.include_router(sites.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
