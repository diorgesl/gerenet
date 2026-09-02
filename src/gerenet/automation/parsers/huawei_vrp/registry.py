from pathlib import Path

import textfsm

_TEMPLATES = Path(__file__).parent / "textfsm"


def parse_template(nome: str, output: str) -> list[dict]:
    """Executa o template TextFSM <nome>.template e devolve as linhas como dicts."""
    with (_TEMPLATES / f"{nome}.template").open(encoding="utf-8") as arquivo:
        fsm = textfsm.TextFSM(arquivo)
    return [dict(zip(fsm.header, linha)) for linha in fsm.ParseText(output)]
