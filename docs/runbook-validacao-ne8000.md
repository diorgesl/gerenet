# Runbook — Task 13: validação fim a fim contra NE8000 real (read-only)

> Fase 1 (cortes 0–2) está implementada e testada (26 tests). Esta é a **validação manual**
> contra um NE8000 real ou de homologação, executada por você — o código não será alterado
> por esta task, exceto o fixture golden e o template TextFSM **se a saída real divergir**.
> Tudo aqui é **read-only no equipamento**: a allowlist do gerenet só aceita comandos `display`.

**Pré-requisitos:** compose dev de pé (`docker compose up -d` — postgres/redis/vault), acesso SSH
read-only ao NE8000 com conta de automação identificável (§19 da spec), e o NE8000 alcançável
pela máquina onde o worker vai rodar.

---

## Passo 1 — Capturar a saída real de `display version` (manual, no equipamento)

Conecte no NE8000 e execute:

```
display version
```

Salve a saída exata em `tests/fixtures/huawei_vrp/ne8000_display_version.txt`.
**Revise o conteúdo antes de versionar** — `display version` não traz configuração, mas confira
mesmo assim (nada de IPs de gerência, hostnames sensíveis etc.). É a única saída do equipamento
que entra no git, e sanitizada.

## Passo 2 — Teste golden com a captura real

Crie `tests/automation/test_parsers_golden.py`:

```python
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.registry import parse_template

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_version.txt")


def test_parse_version_contra_captura_real() -> None:
    saida = FIXTURE.read_text(encoding="utf-8")
    linhas = parse_template("version", saida)
    assert len(linhas) == 1
    assert linhas[0]["version"]  # versão VRP identificada
    assert linhas[0]["uptime"]
```

Rode:

```bash
uv run pytest tests/automation/test_parsers_golden.py -v
```

Se o template não capturar a versão/uptime da saída real (formato diferente, ex.: NE40/VRP5),
ajuste `src/gerenet/automation/parsers/huawei_vrp/textfsm/version.template`, atualize o fixture
e re-rode. Registre no commit o padrão real observado.

## Passo 3 — Registrar device, host key e credencial no gerenet

**3a. Descobrir o fingerprint real (formato OpenSSH `sha256:`)** — troque `<porta>` pela
porta SSH real (ex.: `-p 61341`; `ssh-keygen -lf` lê do stdin com `-f -`, não `-` solto):

```bash
ssh-keyscan -p <porta> -t rsa <ip-mgmt> 2>/dev/null | ssh-keygen -lf -E sha256 -f -   # anotar "SHA256:..."
```

**3b. Cadastrar o device** (nomes VRP derivam do ASN em fases futuras; aqui use um nome de lab):

```bash
uv run gerenet devices add --name <nome> --address <ip-mgmt> --ssh-port <porta> --family ne8000 --role borda
```

**3c. Registrar o fingerprint** (é validado em TODA conexão — fail-closed; erro de digitação
bloqueia a coleta de propósito, e é o comportamento correto):

```bash
uv run gerenet hostkey register <nome> SHA256:<fingerprint-real>
```

**3d. Semear a credencial no Vault** (nunca em banco/arquivo/git — só Vault):

```bash
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet vault seed --username gerenet-auto --password '<senha-da-conta>'
```

> O path no Vault é `gerenet/credential-groups/automacao`. Se este seed já foi feito na Fase 1,
> ele é idempotente — pode rodar de novo sem duplicar.

**3e. Associar o device ao grupo de credencial no banco** (o CLI `devices add` ainda não expõe
`--credential-group` — gap conhecido, anotado no ledger; o SQL abaixo resolve):

```bash
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "insert into credential_groups (name, kind, vault_path) values ('automacao','tacacs_password','gerenet/credential-groups/automacao') on conflict do nothing;"
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "update devices set credential_group_id = (select id from credential_groups where name='automacao') where name='<nome>';"
```

Confira o cadastro:

```bash
uv run gerenet devices list
```

## Passo 4 — Coleta fim a fim (read-only)

**Terminal A — worker:**

```bash
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet-worker
```

**Terminal B — disparar e conferir:**

```bash
uv run gerenet collect run --device <nome>
```

Aguarde o worker processar (log do RQ no Terminal A) e confira:

```bash
uv run gerenet snapshot show <id-do-snapshot>
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "select id, device_id, status from job_runs order by id desc limit 5;"
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "select name, comm_status, vrp_version, uptime, last_collected_at from devices;"
```

**Esperado:**
- snapshot com `status=success` (ou `partial` se um recurso falhar);
- device com `comm_status=ok`, `vrp_version` e `uptime` preenchidos, `last_collected_at` atualizado;
- `job_runs` com `status=success` e `snapshot_id` apontando para o snapshot;
- 2 arquivos brutos em `data/backups/<nome>/<timestamp>/version/version.txt` e
  `data/backups/<nome>/<timestamp>/config_backup/current-configuration.txt`
  (a config bruta **nunca** é versionada nem exibida em logs — `data/` é gitignored).

## Passo 5 — Se algo falhar

- **`HostKeyMismatch`**: o fingerprint registrado não confere com o do servidor — refaça o
  passo 3a/3c. É fail-closed: nenhum comando roda com host key não validada.
- **`CommandNotAllowed`**: algum comando fora da allowlist `^display` — não acontece com os
  coletores atuais; se ocorrer, é bug — reporte.
- **Falha de conexão/timeout**: confira alcance, porta 22 e conta; nada é escrito no equipamento.
- **Snapshot `error`/`partial`**: `snapshot show <id>` exibe `resources`/`errors`; o erro por
  recurso fica no `AuditEvent` (`type='collect.errors'`).

## Passo 6 — Commit

```bash
git add -A
git commit -m "feat: validação fim a fim da coleta contra NE8000 real

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

**Regras inegociáveis:** nenhuma credencial em git/banco/logs; nenhum comando fora da allowlist;
nenhum backup/config bruto versionado; nada de escrita no equipamento (esta fase é read-only).

---

## Critérios de aceite (cortes 0–2, do plano)

Executada em 2026-09-02 contra NE8000 real (VRP 8.240, gerência na porta 61341).

- [x] `uv run pytest` verde com o compose de pé (32 tests, golden real incluso)
- [x] CLI: `devices add|list`, `hostkey register`, `vault seed`, `collect run`, `snapshot show` funcionando
- [ ] API: `/healthz`, CRUD de devices autenticado, `POST /devices/{id}/collect` (202/409/404), snapshots
      — coberta pela suíte (32 passed); sem chamada manual via curl nesta execução
- [x] Coleta real read-only de 1 NE8000: snapshot `success` com `version` parseado (8.240 + uptime),
      backup em `data/backups/ne8k-lab/` (config 172.6K, gitignored), device atualizado
      (`comm_status=ok`, `vrp_version=8.240`, `last_collected_at`), `job_runs`/`audit_events` íntegros
- [x] Nenhuma credencial em git/banco/logs; host key validada antes de toda conexão (fail-closed
      demonstrado ao vivo: fingerprint errado ⇒ coleta recusada sem executar comando);
      nenhum comando fora da allowlist

Observações da execução: worker no macOS precisa de `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`
(crash do fork do RQ × runtime ObjC — não afeta container Linux); `ssh-keyscan -t rsa` não basta
se o servidor negocia outra chave — registrar a que o paramiko recebe (o erro de host key mostra).
