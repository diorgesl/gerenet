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
from gerenet.domain.services import community_plan as svc
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


def _device_apontando(db_session, nome: str, arquivo: Path, *, asn: int | None = 61785) -> int:
    """Equipamento cuja coleta aponta para um arquivo que o teste escreve.

    O caminho, e não o texto: é o caminho que o snapshot guarda e o
    `texto_backup` lê o arquivo do disco a partir dele — quem escreve (e quem
    apaga) o arquivo é o teste.
    """
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.9", asn=asn), actor="cli"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            raw_files={"config_backup": [str(arquivo)]},
        )
    )
    db_session.commit()
    return device.id


def _device_com_config(
    db_session, tmp_path: Path, nome: str, texto: str, *, asn: int | None = 61785
) -> int:
    """Equipamento com a coleta de um texto qualquer.

    Existe para o caso que fixture nenhuma cobre: o plano ativo de **outro** ASN
    principal (a recusa do serviço, R28). O ASN principal sai da configuração
    (`bgp <asn>`), como na proposta — e o `asn` do cadastro é o reserva, que o
    caso sem `bgp` na configuração deixa vazio.
    """
    arquivo = tmp_path / f"{nome}.txt"
    arquivo.write_text(texto, encoding="utf-8")
    return _device_apontando(db_session, nome, arquivo, asn=asn)


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


def test_validar_de_equipamento_sem_coleta_sai_com_erro(db_session) -> None:
    """R43: `--device X` sem leitura de X não valida — e não atesta alinhamento.

    A comparação precisa das duas metades: o plano ativo e a leitura do
    equipamento. Faltando a segunda, o `validar_plano` devolveria o mesmo vazio
    de "plano sem achado" e o comando sairia com 0 — atestando alinhamento numa
    execução que não leu nada.
    """
    com_plano = _device(db_session, "ne-cli-plano-09", "comunidades_edge.txt")
    assert runner.invoke(app, ["communities", "plan", "adotar", str(com_plano)]).exit_code == 0
    sem_coleta = _device_sem_snapshot(db_session, "ne-cli-plano-10")

    resultado = runner.invoke(app, ["communities", "plan", "validar", "--device", str(sem_coleta)])
    assert resultado.exit_code == 1, resultado.output
    # A mensagem é a do serviço, com o equipamento: o operador sabe qual coleta
    # falta. E nada foi comparado — não há lista de achados nenhuma.
    assert f"Equipamento {sem_coleta} não tem coleta" in resultado.output
    assert "Achados" not in resultado.output
    assert "alinhados" not in resultado.output


def test_validar_sem_leitura_nenhuma_nao_atesta_alinhamento(db_session, tmp_path: Path) -> None:
    """R43, o residual: o snapshot cujo arquivo de configuração sumiu não é leitura.

    O equipamento conta como quem tem coleta (a linha do snapshot ficou), mas o
    `texto_backup` devolve "" quando o arquivo não está mais lá e o
    `_leitura_do_device` devolve `None`: a validação seguiria sem comparar nada e
    sairia com 0 dizendo "alinhados". Sem `--device` quem responde é a lista de
    `equipamentos_com_coleta` mais a checagem de leitura.
    """
    arquivo = tmp_path / "sumiu.txt"
    arquivo.write_text(
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n"
        "bgp 61785\n",
        encoding="utf-8",
    )
    device_id = _device_apontando(db_session, "ne-cli-plano-11", arquivo)
    assert runner.invoke(app, ["communities", "plan", "adotar", str(device_id)]).exit_code == 0
    arquivo.unlink()

    resultado = runner.invoke(app, ["communities", "plan", "validar"])
    assert resultado.exit_code == 1, resultado.output
    assert "coleta legível" in resultado.output
    assert "alinhados" not in resultado.output


def test_validar_com_coleta_e_plano_limpo_atesta_alinhamento(db_session, tmp_path: Path) -> None:
    """O outro lado: com leitura e sem achado, o exit 0 continua saindo.

    A guarda nova não pode transformar o caso bom em erro — um plano que a
    configuração cumpre segue saindo com a frase de alinhado, senão o portão da
    automação ficaria vermelho para sempre.
    """
    device_id = _device_com_config(
        db_session, tmp_path, "ne-cli-plano-12",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n"
        "bgp 61785\n",
    )
    assert runner.invoke(app, ["communities", "plan", "adotar", str(device_id)]).exit_code == 0

    resultado = runner.invoke(app, ["communities", "plan", "validar", "--device", str(device_id)])
    assert resultado.exit_code == 0, resultado.output
    assert "alinhados" in resultado.stdout
    assert "Achados" not in resultado.stdout


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


def test_adotar_sem_asn_principal_sai_com_erro(db_session, tmp_path: Path) -> None:
    """R31: proposta sem ASN principal não vira plano — mensagem, não traceback.

    O ASN principal sai do `bgp <asn>` da configuração e, na falta dele, do
    cadastro do equipamento. Sem os dois a proposta não tem ASN principal e o
    serviço recusa (`ValidationError`), que o CLI traduz em mensagem e exit 1.
    """
    device_id = _device_com_config(
        db_session, tmp_path, "ne-cli-plano-13",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n",
        asn=None,
    )
    resultado = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert resultado.exit_code == 1, resultado.output
    assert f"O equipamento {device_id} não tem ASN" in resultado.output
    # `SystemExit` do `typer.Exit`, e não a exceção do serviço subindo: o que
    # separa a mensagem do operador do traceback.
    assert isinstance(resultado.exception, SystemExit)
    assert "Traceback" not in resultado.output


def test_adotar_de_outro_equipamento_conta_o_plano_em_vigor(db_session, tmp_path: Path) -> None:
    """R40: a segunda adoção conta o plano em vigor, não a proposta que a pediu.

    Dois equipamentos com o mesmo ASN principal: a adoção do segundo é
    idempotente e devolve o plano que já estava. Os números impressos são os do
    plano **em vigor** — aqui contados pelas mesmas duas funções que o `show` e o
    `GET /plan` usam —, e o controle negativo é a proposta do segundo
    equipamento, que é bem menor: um resumo que a contasse daria outros números.
    """
    primeiro = _device(db_session, "ne-cli-plano-14", "comunidades_edge.txt")
    primeira = runner.invoke(app, ["communities", "plan", "adotar", str(primeiro)])
    assert primeira.exit_code == 0, primeira.output

    segundo = _device_com_config(
        db_session, tmp_path, "ne-cli-plano-15",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n"
        "bgp 61785\n",
    )
    proposta = svc.propor_adocao(db_session, segundo)

    segunda = runner.invoke(app, ["communities", "plan", "adotar", str(segundo)])
    assert segunda.exit_code == 0, segunda.output
    assert "já existia" in segunda.stdout
    assert "Plano adotado" not in segunda.stdout

    em_vigor = svc.montar_plano_out(db_session, svc.obter_plano(db_session))
    assert _numeros(segunda.stdout) == (
        str(len(em_vigor.classes)), str(len(em_vigor.portoes)), str(len(em_vigor.alvos))
    )
    assert _numeros(segunda.stdout) == _numeros(primeira.stdout)
    assert len(proposta.plano.classes) != len(em_vigor.classes)
    assert len(proposta.plano.portoes) != len(em_vigor.portoes)


def test_adotar_resumo_flexiona_a_contagem(db_session) -> None:
    """O resumo escreve português: "1 alvo" no singular, "3 portões" no plural.

    O alvo só existe com o recurso de peers da coleta: é ele que põe o alvo de
    pé e dá a contagem — e a contagem 1 é a que separa "alvo" de "alvos".
    """
    device_id = _device(
        db_session, "ne-cli-plano-16", "comunidades_edge.txt",
        recursos={"bgp_peers": [{"peer": "100.127.190.5", "estado": "established"}]},
    )
    adocao = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert adocao.exit_code == 0, adocao.output
    assert "3 portões" in adocao.stdout
    assert "1 alvo." in adocao.stdout
