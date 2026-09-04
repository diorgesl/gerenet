"""Render da intenção em comandos VRP (spec ciclo B §5)."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent / "templates" / "huawei_vrp"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def _render_template(nome: str, contexto: dict) -> str:
    """Renderiza o template `nome` (sem sufixo) com `contexto`; sem `\n` final."""
    return _env.get_template(nome + ".j2").render(**contexto).rstrip("\n")
