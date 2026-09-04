"""Servir o build da SPA (web/dist) com fallback para rotas do client (ciclo C).

A SPA é servida pela própria API (mesma origem, sem CORS): o index.html só
cai nas rotas GET que não começam com /api. Assets de /assets/ são imutáveis
(hash no nome). Sem build presente, nada é registrado.
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
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        # Contenção no diretório do build (resolve segue symlinks; is_relative_to
        # bloqueia traversal — ex.: %2e%2e / .. decodificado pelo uvicorn).
        raiz = static_dir.resolve()
        alvo = (static_dir / path).resolve()
        if not alvo.is_relative_to(raiz):
            raise HTTPException(status_code=404)
        if path and alvo.is_file():
            cabecalhos = (
                {"Cache-Control": "public,max-age=31536000,immutable"}
                if path.startswith("assets/")
                else {}
            )
            return FileResponse(alvo, headers=cabecalhos)
        # fallback SPA: qualquer rota do client (react-router) → index.html
        return FileResponse(index)

    @router.api_route(
        "/{path:path}",
        methods=["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    def _outros_metodos(path: str) -> None:
        # Rota inexistente/ imprópria para o método: 404, não 405 (contrato
        # pré-fallback; o catch-all resposta só o que sobrou — rotas reais,
        # registradas antes, vencem nos métodos que suportam).
        raise HTTPException(status_code=404)

    app.include_router(router)
