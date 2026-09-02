# Design — Fase 1: Inventário e coleta read-only (gerenet)

**Data:** 2026-09-02
**Escopo:** arquitetura base do repositório + Fase 1 do roadmap (§22) — inventário de equipamentos e coleta read-only.
**Referências:** [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](../../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md) — princípios §3, arquitetura §4, inventário §5, reconciliação §10, dados §14, acesso §17, auditoria §18, segurança §19, observabilidade §20, testes §21, fases §22, critérios de aceite do MVP §24 e **decisões registradas §25 (2026-09-02)**.

## 1. Objetivo e escopo da Fase 1

Entregar a fundação do sistema **gerenet** (pacote `gerenet`, subdomínio `gerenet.app.diorg.es`): cadastro de equipamentos Huawei, acesso seguro e read-only via SSH/TACACS+, coleta de estado operacional com backup de configuração e inventário de interfaces e peers BGP — satisfazendo o critério do MVP "inventário de interfaces e peers" (§24) com trilha de auditoria básica.

**No primeiro corte da coleta:** `version` (versão VRP/uptime), `interfaces` (inventário), `bgp_peers` (estado + contagem de rotas) e backup de `display current-configuration`. Coletores LDP/L2VC/VSI entram **na mesma Fase 1**, depois do núcleo validado contra equipamento real, um parser por vez (§22.1).

**Fora de escopo da F1:** detecção de divergência e reconciliação (Fase 2), geração/aplicação de mudanças (Fase 3), interface web, perfis de usuário/dupla aprovação (Fase 2+, §17), cadastro de sites/POPs (tabela `sites` na Fase 2), IRR/RPKI, XPL, Vault real em produção além de um secret group.

**Contexto de desenvolvimento:** acesso real read-only a equipamentos (produção/homologação) disponível durante o desenvolvimento; parsers nascem de saídas reais capturadas. Nenhuma automação de escrita em nenhuma hipótese nesta fase.

## 2. Decisões de arquitetura

1. **Monólito modular em camadas** (aprovado): um repositório, um pacote, fronteiras por pasta; dependências fluem `automation → domain → api`, nunca ao contrário. `cli` e `worker` são portas de entrada do mesmo núcleo.
2. **Fila RQ + Redis** (spec §4.1: Celery *ou* RQ): leve para a F1; a camada de fila fica isolada para troca futura.
3. **Nornir com inventário vindo do PostgreSQL** via plugin de inventário próprio (sem `hosts.yaml` como fonte de verdade); conexão via Netmiko (`huawei_vrp`).
4. **Snapshot em JSONB** em `device_snapshots`; saída bruta em volume em disco (não em git); normalização em tabelas fica para a Fase 2, apenas para recursos que o motor de divergência precisar comparar objeto a objeto.
5. **Vault já na F1** (§25.9: TACACS+): interface `SecretStore` (implementação HashiCorp Vault); dev roda servidor Vault dev no compose; credenciais nunca em banco/YAML/git (§19).
6. **Host keys validados** em toda conexão; registro explícito via CLI (ou `--accept-new-key` de uso único).
7. **API key única** na F1 para a API; perfis §17 na Fase 2.
8. **Deploy Docker + Traefik** (padrão da casa): compose dev local e compose de produção no subdomínio `gerenet.app.diorg.es`.
9. **Métricas Prometheus** (`/metrics` na API e no worker) desde a F1 (§25.15); Zabbix na Fase 6.

## 3. Estrutura do repositório

```
BGP/                                  (git init na F1)
├── pyproject.toml                    # uv; Python 3.12+
├── compose.yaml                      # dev: postgres, redis, vault, api, worker
├── deploy/
│   ├── docker/                       # compose de produção + .env (ignorado)
│   └── traefik/                      # configuração do subdomínio
├── alembic/
├── src/gerenet/
│   ├── api/                          # FastAPI; routers /api/v1/*
│   ├── domain/                       # SQLAlchemy + schemas Pydantic + serviços
│   ├── automation/
│   │   ├── inventory.py              # plugin de inventário Nornir (leitura do banco)
│   │   ├── collectors.py             # catálogo de coletores por recurso + allowlist
│   │   ├── netmiko_conn.py           # conexão + validação de host key + timeouts
│   │   └── parsers/huawei_vrp/
│   │       ├── textfsm/*.template
│   │       └── registry.py
│   ├── worker/                       # tarefas RQ + locks Redis
│   ├── cli/                          # Typer
│   ├── secrets/                      # interface SecretStore (Vault)
│   ├── config.py                     # pydantic-settings (env)
│   └── observability.py              # métricas Prometheus
├── tests/
│   ├── fixtures/                     # saídas `display` reais sanitizadas
│   └── golden/                       # saída esperada dos parsers
├── docs/superpowers/specs/           # specs de design (este arquivo)
└── .gitignore                        # + .claude/settings.local.json
```

## 4. Modelo de dados da F1

Tabelas iniciais (Alembic desde a primeira):

- **`devices`** — nome único, endereço de gerenciamento, fabricante, modelo, família (NE8000/NE40/S6730…), função, site/POP (string livre na F1), versão VRP e uptime (últimos coletados), status admin (ativo/desativado), status de comunicação (ok/falha/inalcançável), contagem de falhas consecutivas, data da última coleta, host key fingerprint, `credential_group_id`, tags, timestamps. Desativação em vez de exclusão física (§14.1).
- **`credential_groups`** — nome único, tipo (por ora: tacacs_password), caminho no Vault. A senha vive apenas no Vault.
- **`device_snapshots`** — `device_id`, início/fim, status (sucesso/erro/parcial), payload JSONB por recurso (`version`, `interfaces`, `bgp_peers`, …), erros por recurso (JSONB), caminhos dos arquivos brutos no volume, hash, duração.
- **`job_runs`** — origem (api/cli), autor (API key/usuário), device, tipo (collect), status, timestamps, duração, `snapshot_id`. Auditoria das execuções.
- **`audit_events`** — eventos imutáveis (tipo, autor, detalhes JSONB, timestamp): cadastro/edição/desativação de device, registro de host key, disparo de coleta. Passwords/segredos nunca em detalhes (§18).

## 5. Segredos e acesso aos equipamentos

- Conta de automação única na F1 (grupo padrão criado no seed), autenticada via **TACACS+** (§25.9): o app apresenta usuário/senha no login SSH.
- Path Vault: `gerenet/credential-groups/<nome>`; dev: Vault dev no compose + `gerenet vault seed`; produção: secret criado antes do primeiro deploy (runbook).
- **Host keys:** `gerenet hostkey register <device>` grava o fingerprint SHA-256 esperado; toda conexão falha se o fingerprint divergir (§19 — validar host keys). `gerenet collect run --accept-new-key <device>` existe apenas como procedimento consciente de primeiro registro.
- Nenhuma credencial em banco, YAML, git ou logs; saídas brutas e logs são revisados/mascarados se expuserem segredo (§18).

## 6. Motor de coleta

### 6.1 Catálogo de coletores (allowlist read-only)

Um coletor por recurso, registrado em `collectors.py`; cada entrada declara: recurso, comandos, parser TextFSM, e para quais famílias se aplica. Comandos candidatos do núcleo (a confirmar contra saídas reais na implementação):

| Recurso | Comando(s) candidato(s) |
|---|---|
| version | `display version` |
| config_backup | `display current-configuration` |
| interfaces | `display interface brief` (+ `display ip interface brief` se necessário) |
| bgp_peers | `display bgp peer` + contagem de rotas por peer (ex.: `display bgp ipv4/ipv6 unicast peer <ip> verbose` ou equivalente que a saída real mostrar) |

Nenhum comando fora da allowlist é executado. Falha/parse incompleto de um recurso não derruba a coleta: status **parcial**, erro registrado por recurso no snapshot.

### 6.2 Parsers

TextFSM (spec §4.2), templates em `automation/parsers/huawei_vrp/textfsm/`, cada um coberto por testes golden com fixtures reais sanitizadas (remover quaisquer segredos antes de versionar). Variações entre versões do VRP viram templates/ajustes novos com fixture própria (§21.1 — parsing de comandos `display`).

### 6.3 Fluxo de uma coleta

Disparo (API/CLI) → `job_run` → lock Redis por device (`SETNX` + TTL) → conexão Netmiko com validação de host key e credencial do Vault → execução dos comandos da allowlist (timeouts por comando) → bruto gravado no volume → parse por recurso → snapshot JSONB + campos de estado do device atualizados → lock liberado → `job_run` concluído (sucesso/parcial/erro + duração). Nenhuma etapa deixa estado inconsistente.

- **Concorrência (§25.14):** lock por equipamento (um job por vez por device; segundo disparo com job pendente/ativo é recusado com 409/erro claro); workers 2–4 processos (limite global configurável). Quando a Fase 2 criar POPs, o limite por POP usa o mesmo mecanismo de semáforo.
- **Falhas:** 1 retry curto para falha transitória de conexão; falha de comunicação incrementa contagem no device e atualiza status; timeout padrão configurável.

## 7. API e CLI

**API** `/api/v1` (auth: header `X-API-Key`; token em env/secret):

- `GET /devices` · `POST /devices` · `GET /devices/{id}` · `PATCH /devices/{id}` (inclui desativar)
- `POST /devices/{id}/collect` → enfileira, devolve `job_run`
- `GET /devices/{id}/snapshots` · `GET /snapshots/{id}`
- `GET /healthz` · `GET /metrics`

**CLI (Typer)** — `gerenet devices add|list|disable`, `gerenet collect run --device <id|nome> | --all [--accept-new-key]`, `gerenet snapshot show <id> [--resource <nome>]`, `gerenet hostkey register <device>`, `gerenet vault seed`, `gerenet snapshot prune --keep N`.

## 8. Observabilidade

Métricas §20.1 no `/metrics` (API e worker): duração/sucesso/falha por job e device, devices inalcançáveis, idade da última coleta, tamanho da fila. Logs estruturados.

## 9. Deploy

- **Dev:** `compose.yaml` — postgres, redis, vault (dev), api (hot-reload), worker; volume `backups/`; `.env` local fora do repo.
- **Produção (`deploy/docker`):** mesmo stack + rede Traefik `proxy` compartilhada, labels `traefik.http.routers.gerenet.*`, subdomínio `gerenet.app.diorg.es`, TLS; `.env` ignorado; runbook curto (seed do Vault → deploy). Worker e API sobem juntos.
- Retenção de backups brutos no volume configurável (`prune`).

## 10. Testes

- **Unit:** parsers (golden), regras de serviço (estado de device, desativação), locks Redis (mock), `SecretStore` (Vault dev/testcontainers).
- **Fixtures:** saídas reais capturadas, sanitizadas, versionadas em `tests/fixtures/`.
- **Integração contra equipamento real:** passo **manual e controlado** (read-only), nunca automatizado contra produção; faz parte da validação de cada corte.
- CI: pytest + ruff no repositório (plataforma conforme o que a operação já usa).

## 11. Cortes de entrega

| Corte | Entrega | Validação |
|---|---|---|
| 0 | Repo + uv + compose dev + Alembic + `/healthz` | compose sobe, healthcheck ok |
| 1 | Cadastro/consulta/desativação de devices + Vault dev + registro de host key | API + CLI funcionando contra compose dev |
| 2 | Coleta `version` + backup de config via fila/lock | fim a fim contra 1 device real read-only |
| 3 | Parsers `interfaces` + `bgp_peers` (golden) + snapshot completo | inventário de interfaces e peers de 1 NE8000 (§24) |
| 4 | Observabilidade mínima + CLI polido + runbook Traefik | `/metrics` populado; deploy em `gerenet.app.diorg.es` |
| 5 | Coletores LDP/L2VC/VSI contra saídas reais | 1 switch MPLS coletado |

**Critério de aceite da Fase 1:** coleta read-only de **1 NE8000 + 2 switches** com inventário de interfaces/peers BGP, backup de configuração em volume com retenção, e trilha `job_runs`/`audit_events` íntegra.

## 12. Riscos e mitigações

- **Variação de saída entre versões VRP** → golden por versão; coletor marca família/versão no snapshot.
- **Saídas grandes (`display current-configuration`)** → bruto em volume, nunca no banco; timeout e tamanho máx. configuráveis.
- **Segredo em saída bruta** → Huawei cifra por padrão; revisão/mascaramento obrigatório nas fixtures; logs nunca gravam saída bruta.
- **Fila/worker com pouca maturidade** → camada de fila isolada; locks desde o início; RQ trocável por Celery sem tocar o domínio.
- **Netmiko/Nornir × VRP específico** → camada de conexão fina e testável; fallback documentado para conexão direta Netmiko se o Nornir 3.x atrapalhar.
