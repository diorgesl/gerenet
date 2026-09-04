"""Servir o build da SPA (web/dist) com fallback para rotas do client (ciclo C).

Mesma origem do backend (spec §3.1): sem CORS; o index.html só cai nas rotas
GET que não começam com /api. Assets de /assets/ são imutáveis (hash no nome).
"""
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse


def montar_spa(app: FastAPI, static_dir: Path) -> None:
    """Registra o fallback SPA quando o build existe; senão, nada acontece."""
    index = static_dir / "index.html"
    if not index.exists():
        return

    router = APIRouter(include_in_schema=False)

    @router.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        alvo = static_dir / path
        if path and alvo.is_file():
            cabecalhos = (
                {"Cache-Control": "public,max-age=31536000,immutable"}
                if path.startswith("assets/")
                else {}
            )
            return FileResponse(alvo, headers=cabecalhos)
        # fallback SPA: qualquer rota do client (react-router) → index.html
        return FileResponse(index)

    app.include_router(router)
