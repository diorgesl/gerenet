"""CLI do plano de communities (spec §9/§11): CliRunner e banco real.

O CLI é a consulta do operador ao lado da página: lê o plano da SoT, compara com
a coleta e adota. Nada aqui vai ao equipamento — a origem é o snapshot já
gravado, e mudar o roteador continua sendo change request.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

runner = CliRunner()
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _device(db_session, nome: str, fixture: str, *, recursos: dict | None = None) -> int:
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.6", asn=61785), actor="cli"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            # O caminho da fixture, e não o texto dela: é o caminho que o
            # snapshot guarda e o `texto_backup` lê o arquivo do disco a partir
            # dele (`automation/snapshots.py:16-20`).
            raw_files={"config_backup": [str(FIXTURES / fixture)]},
            resources=recursos,
        )
    )
    db_session.commit()
    return device.id


def _device_sem_snapshot(db_session, nome: str) -> int:
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.5", asn=61785), actor="cli"
    )
    db_session.commit()
    return device.id


def _device_com_config(db_session, tmp_path: Path, nome: str, texto: str) -> int:
    """Equipamento com a coleta de um texto qualquer.

    Existe para o caso que fixture nenhuma cobre: o plano ativo de **outro** ASN
    principal (a recusa do serviço, R28). O ASN principal sai da configuração
    (`bgp <asn>`), como na proposta.
    """
    arquivo = tmp_path / f"{nome}.txt"
    arquivo.write_text(texto, encoding="utf-8")
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.9", asn=61785), actor="cli"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            raw_files={"config_backup": [str(arquivo)]},
        )
    )
    db_session.commit()
    return device.id


def _numeros(texto: str) -> tuple[str, ...]:
    """Os três números do resumo da adoção (classes, portões e alvos em vigor)."""
    achado = re.search(r"(\d+) classes, (\d+) portões, (\d+) alvos", texto)
    assert achado is not None, texto
    return achado.groups()


def test_show_sem_plano_avisa(db_session) -> None:
    resultado = runner.invoke(app, ["communities", "plan", "show"])
    assert resultado.exit_code == 0
    assert "Nenhum plano" in resultado.stdout


def test_adotar_e_depois_mostrar(db_session) -> None:
    device_id = _device(db_session, "ne-cli-plano-01", "comunidades_edge.txt")
    adocao = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert adocao.exit_code == 0, adocao.output
    assert "61785" in adocao.stdout

    show = runner.invoke(app, ["communities", "plan", "show"])
    assert show.exit_code == 0
    assert "com-TRANSITO-FULL" in show.stdout


def test_show_traz_quem_aplica_e_quem_testa(db_session) -> None:
    """As duas colunas da §11 saem do `PlanoOut`, que resolve o corpus citado.

    O `com-TECMAIS-v4` é aplicado pela route-policy `CUSTOMER-BGP-v4` por
    **corpus** (`apply community com-EXPORT-UPSTREAM-v4`, cujo corpo é o
    `61785:3001`) e testado pelos dois portões de exportação. Lido só do
    `PlanoLido` — que não tem estas colunas — a linha sairia vazia e o operador
    leria "ninguém" para a classe que a validação acusa aplicada e não testada.
    """
    device_id = _device(db_session, "ne-cli-plano-02", "comunidades_edge.txt")
    assert runner.invoke(app, ["communities", "plan", "adotar", str(device_id)]).exit_code == 0

    show = runner.invoke(app, ["communities", "plan", "show"])
    assert show.exit_code == 0, show.output
    assert "aplicam=[CUSTOMER-BGP-v4]" in show.stdout
    assert "testam=[RouteExportCheck, RouteExportCheckV6]" in show.stdout
    # A classe só citada (`if-match community-filter com-TRANSITO-FULL`) não é
    # aplicada nem testada: citação não é uso.
    linha = next(linha for linha in show.stdout.splitlines() if "com-TRANSITO-FULL" in linha)
    assert "aplicam=[]" in linha and "testam=[]" in linha


def test_show_traz_os_portoes_e_o_estado_dos_alvos(db_session) -> None:
    """Os portões do plano e o estado coletado de cada alvo (§9.1/§9.3).

    O `bgp_peers` da coleta é o que dá estado ao alvo: sem o recurso, os alvos
    param de pé e o plano sai sem nenhum. Com ele, o alvo de pé é gravado e o
    `show` diz o estado — que é do **equipamento**, não da SoT.
    """
    device_id = _device(
        db_session, "ne-cli-plano-03", "comunidades_edge.txt",
        recursos={"bgp_peers": [{"peer": "100.127.190.5", "estado": "established"}]},
    )
    assert runner.invoke(app, ["communities", "plan", "adotar", str(device_id)]).exit_code == 0

    show = runner.invoke(app, ["communities", "plan", "show"])
    assert show.exit_code == 0, show.output
    assert "aceitas=[com-TAMANHO-2, com-TECMAIS-v4, com-PARCEIROS_CDN-v4]" in show.stdout
    assert "recusadas=[com-ONLY-CDN]" in show.stdout
    assert "estado=established" in show.stdout


def test_validar_lista_os_achados(db_session) -> None:
    device_id = _device(db_session, "ne-cli-plano-04", "comunidades_edge.txt")
    runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    resultado = runner.invoke(app, ["communities", "plan", "validar", "--device", str(device_id)])
    # O achado é `critico` (§8.1) e o comando sai com 1: é o que um roteiro de
    # verificação lê para decidir se o plano está publicável.
    assert resultado.exit_code == 1, resultado.output
    assert "classe_aplicada_nao_testada" in resultado.stdout


def test_validar_sem_plano_nao_afirma_plano_alinhado(db_session) -> None:
    """Sem plano não há o que comparar — e "alinhados" seria conclusão sem leitura.

    `validar_plano` devolve vazio nos dois casos (plano ausente e plano sem
    achado), então quem distingue é a consulta ao plano: a frase de "nada a
    fazer" só vale quando existe plano para comparar.
    """
    resultado = runner.invoke(app, ["communities", "plan", "validar"])
    assert resultado.exit_code == 0, resultado.output
    assert "Nenhum plano" in resultado.output
    assert "alinhados" not in resultado.output


def test_adotar_sem_coleta_sai_com_erro(db_session) -> None:
    device_id = _device_sem_snapshot(db_session, "ne-cli-plano-05")
    resultado = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert resultado.exit_code == 1, resultado.output
    # `SystemExit` e não a exceção do serviço: é o que separa a mensagem do traceback.
    assert "coleta" in resultado.output.lower()


def test_adotar_de_novo_nao_mente_sobre_a_escrita(db_session) -> None:
    """R40: com o mesmo ASN principal o serviço devolve o plano e não grava.

    Os números contados são os do plano **em vigor** (o mesmo que o `show`
    devolve), e não os da proposta deste equipamento — e quem diz que nada foi
    gravado é a linha, que sai com "já existia".
    """
    device_id = _device(db_session, "ne-cli-plano-06", "comunidades_edge.txt")
    primeira = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert primeira.exit_code == 0, primeira.output
    assert "Plano adotado" in primeira.stdout

    segunda = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert segunda.exit_code == 0, segunda.output
    assert "já existia" in segunda.stdout
    assert "Plano adotado" not in segunda.stdout
    # Números do plano em vigor: os mesmos da primeira adoção.
    assert _numeros(segunda.stdout) == _numeros(primeira.stdout)


def test_adotar_plano_de_outro_asn_principal_recusa(db_session, tmp_path: Path) -> None:
    """R28: o plano ativo de outro ASN principal recusa antes de escrever.

    Os filhos do plano não têm recorte por plano ativo, então substituir pediria
    mudar o modelo: a resposta é a recusa, e o plano ativo continua o primeiro.
    """
    primeiro = _device(db_session, "ne-cli-plano-07", "comunidades_edge.txt")
    assert runner.invoke(app, ["communities", "plan", "adotar", str(primeiro)]).exit_code == 0

    outro = _device_com_config(
        db_session, tmp_path, "ne-cli-plano-08",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n"
        "bgp 65001\n",
    )
    resultado = runner.invoke(app, ["communities", "plan", "adotar", str(outro)])
    assert resultado.exit_code == 1, resultado.output
    assert "Já existe plano ativo" in resultado.output

    show = runner.invoke(app, ["communities", "plan", "show"])
    assert "ASN principal: 61785" in show.stdout
    assert "ASN principal: 65001" not in show.stdout
