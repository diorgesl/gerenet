# Runbook — observabilidade (métricas e Grafana)

Vale para a Fase 6, parte 1: coleta periódica, resumo de divergência na coleta e
o endpoint Prometheus.

## O que a plataforma expõe

`GET /metrics`, no mesmo processo da API, com os itens do §20.1: equipamentos por
estado de comunicação, idade do snapshot e falhas consecutivas por equipamento,
divergências por severidade, peers BGP por estado, L2VC e VSI por estado,
mudanças por status, fila de jobs e duração de tarefa (p50/p95).

O endpoint pertence à **rede de gerência** (§19): não tem autenticação de sessão,
como o `/healthz`. Com `GERENET_METRICS_TOKEN` preenchido, ele exige
`Authorization: Bearer <token>` — e o scrape precisa mandar o mesmo valor.

O worker **não** expõe `/metrics`: cada job roda num processo filho (`os.fork`) e
métricas em memória morreriam com ele. As métricas de job vêm do `job_runs`, que
é durável.

As séries de divergência **não** distinguem comparação parcial: o campo `parcial`
do resumo aparece no card do dashboard, não em painel. Publicá-lo como série hoje
viraria ruído — todo equipamento sem sessão no SoT tem comparação parcial, porque
a coleta pula o recurso verbose nesse caso.

### Ligar o token

O valor vai no `.env` da raiz, que é gitignored (o mesmo arranjo dos segredos do
Vault):

```
GERENET_METRICS_TOKEN=<token>
```

Acrescente ao serviço `api` do `compose.yaml` (ou ao ambiente de quem instala):

```yaml
  api:
    environment:
      <<: *app-env
      GERENET_METRICS_TOKEN: ${GERENET_METRICS_TOKEN}
```

Em produção, o scrape lê o token de um **arquivo montado de fora do Git** — o
`prometheus.yml` do repositório é o de dev e não leva token:

```yaml
  - job_name: gerenet
    metrics_path: /metrics
    authorization:
      credentials_file: /etc/prometheus/gerenet-metrics-token
    static_configs:
      - targets: ["api:8000"]
```

O arquivo vem do `.env`/secret do orquestrador, e é o caminho que evita colar o
valor num arquivo versionado. O **valor** do token nunca vai para nenhum arquivo
**do repositório**: no dev o compose interpola a variável a partir do ambiente
(o mesmo `.env` gitignored); em produção, ela vem do ambiente da plataforma e o
Prometheus lê o arquivo montado.

Deixar a variável ausente derruba a API na subida, de propósito: o compose
substitui `GERENET_METRICS_TOKEN: ${GERENET_METRICS_TOKEN}` por string vazia, e o
`Settings` recusa token vazio (é o que impede "token vazio = endpoint aberto").
Vale igual para a forma com default vazio, `${GERENET_METRICS_TOKEN:-}`, que só
escreve o mesmo vazio de outro jeito. Por isso o valor tem de estar no `.env`
**antes** do `docker compose up` — e para manter o endpoint sem autenticação,
basta não acrescentar a linha ao serviço `api`.

Conferência, com o token ligado:

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/metrics                    # 401
curl -s -H 'Authorization: Bearer <token>' localhost:8000/metrics | head
```

## Dev: o Prometheus do compose e o painel no seu Grafana

O `prometheus` do compose sobe no `up -d` comum e já vem com o scrape de
`api:8000/metrics` (`docker/observability/prometheus.yml`); o `/targets` dele, em
http://localhost:9090, mostra o alvo. O **Grafana** é opcional, atrás do profile
`observabilidade`:

```bash
docker compose up -d grafana                      # só o Grafana (e o Prometheus)
docker compose --profile observabilidade up -d    # a stack inteira
```

Quem já tem Grafana não precisa desse serviço: importe o painel
`gerenet — operação` (`docker/observability/grafana/dashboards/gerenet.json`) no
seu, em *Dashboards → New → Import → Upload JSON file*, mapeando os painéis para
o datasource Prometheus que já existe. O Grafana do profile é provisionado com
esse mesmo JSON e um datasource apontando para o `prometheus` do compose, com
acesso anônimo como viewer.

Sem dado nos painéis: confira primeiro o `/targets` (alvo UP) e depois
`curl -s localhost:8000/metrics | head`. Com o token ligado, o scrape também
precisa do bloco `authorization` — via `credentials_file` apontando para um
arquivo **fora do repositório**, nunca com o valor em arquivo versionado.

Os dois painéis de idade (**Coleta mais antiga** e **Idade da coleta por
equipamento**) aparecem "No data" até o primeiro snapshot de algum equipamento: a
série `gerenet_snapshot_age_seconds` não existe para quem nunca foi coletado, e
série ausente não é zero. Depois do primeiro snapshot, o painel por equipamento
lista só os equipamentos já coletados.

No Grafana do profile `observabilidade`, o acesso anônimo é viewer: para editar
os painéis é preciso entrar com o admin, que nasce com a credencial padrão do
primeiro boot (`admin`/`admin`, com o prompt de troca de senha no primeiro
acesso). A conferência por `curl` usa `POST /login`, que é a rota real:

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"user":"admin","password":"admin"}' http://localhost:3000/login
# 200 {"message":"Logged in","redirectUrl":"/"}
```

`POST /api/login` não existe. Com o acesso anônimo ligado, a sonda errada devolve
404 (o pedido conta como assinado e chega ao roteador; sem sessão nenhuma, o
middleware do grupo `/api` responderia 401 antes disso).

## Produção

Aponte o Prometheus de casa para o `/metrics` da plataforma, pela rede de
gerência. O `prometheus.yml` e o JSON do dashboard do repo servem de ponto de
partida (o job de dev, sem token); o resto é ajuste local — inclusive o token,
pelo arquivo montado da seção anterior. Se a API estiver atrás de proxy, o
`/metrics` precisa ser roteado como o resto.

**Alerta é de quem instala.** A plataforma entrega as séries para isso
(`gerenet_devices_comm_status`, `gerenet_device_consecutive_failures`,
`gerenet_snapshot_age_seconds`, `gerenet_divergences`); nenhuma alert rule
acompanha o repositório, e o §20.1 não pede nenhuma. O painel é de leitura, não
de alerta — quem opera monta as regras no próprio Prometheus/Grafana.

## Coleta periódica

`GERENET_COLLECT_INTERVAL_MINUTES` (0 = desligado) liga a varredura; o worker
arma na subida, então mudar o valor pede restart do worker. Os números de cada
varredura estão no evento `collect.sweep` da auditoria. A wiki de equipamentos
tem as regras (idade, 2×, recusas).
