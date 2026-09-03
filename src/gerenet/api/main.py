from fastapi import FastAPI

from gerenet.api.routers import bgp_sessions, circuits, contacts, devices, organizations, sites


# uvicorn gerenet.api.main:create_app --factory
def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")
    app.include_router(devices.router)
    app.include_router(devices.snap_router)
    app.include_router(sites.router)
    app.include_router(organizations.router)
    app.include_router(organizations.downstreams_router)
    app.include_router(contacts.router)
    app.include_router(circuits.router)
    app.include_router(bgp_sessions.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
