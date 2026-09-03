from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from gerenet.api.routers import (
    bgp_sessions,
    circuits,
    contacts,
    devices,
    organizations,
    policy_profiles,
    prefix_authorizations,
    sites,
)


async def _erro_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 sem a chave 'input': o corpo enviado (senha etc.) nunca vaza na resposta."""
    erros = [
        {"loc": erro.get("loc"), "msg": erro.get("msg"), "type": erro.get("type")}
        for erro in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": erros})


# uvicorn gerenet.api.main:create_app --factory
def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")
    app.add_exception_handler(RequestValidationError, _erro_validacao)
    app.include_router(devices.router)
    app.include_router(devices.snap_router)
    app.include_router(sites.router)
    app.include_router(organizations.router)
    app.include_router(organizations.downstreams_router)
    app.include_router(contacts.router)
    app.include_router(circuits.router)
    app.include_router(bgp_sessions.router)
    app.include_router(policy_profiles.router)
    app.include_router(prefix_authorizations.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
