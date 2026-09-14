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

### Ligar o token

O valor vai no `.env` da raiz, que é gitignored (o mesmo arranjo dos segredos do
Vault):

```
GERENET_METRICS_TOKEN=<token>
```

O serviço `api` do `compose.yaml` lê a variável do ambiente

```yaml
  api:
    environment:
      <<: *app-env
      GERENET_METRICS_TOKEN: ${GERENET_METRICS_TOKEN}
```

e o scrape manda o mesmo valor:

```yaml
  - job_name: gerenet
    metrics_path: /metrics
    authorization:
      credentials: <mesmo-token>
    static_configs:
      - targets: ["api:8000"]
```

O **valor** nunca vai para o `compose.yaml` nem para qualquer arquivo
versionado: o compose interpola a variável a partir do ambiente. Em produção, ela
vem do ambiente da plataforma.

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

## Dev: Prometheus e Grafana do compose

```bash
docker compose up -d prometheus grafana
```

- Prometheus em http://localhost:9090 (`/targets` mostra o alvo `gerenet`);
- Grafana em http://localhost:3000, acesso anônimo como viewer, com o dashboard
  `gerenet — operação` já provisionado (arquivos em `docker/observability/`).

Sem dado nos painéis: confira primeiro `/targets` (alvo UP) e depois
`curl -s localhost:8000/metrics | head`. Com o token ligado, o job do
`prometheus.yml` precisa do bloco `authorization`.

Os dois painéis de idade (**Coleta mais antiga** e **Idade da coleta por
equipamento**) aparecem "No data" até o primeiro snapshot de algum equipamento: a
série `gerenet_snapshot_age_seconds` não existe para quem nunca foi coletado, e
série ausente não é zero. Depois do primeiro snapshot, o painel por equipamento
lista só os equipamentos já coletados.

O acesso anônimo é viewer: para editar os painéis é preciso entrar com o admin do
Grafana, que nasce com a credencial padrão do primeiro boot (`admin`/`admin`,
com o prompt de troca de senha no primeiro acesso). A conferência por `curl` usa
`POST /login`, que é a rota real:

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
gerência. Os dois arquivos que importam são os do repo (`prometheus.yml` e o JSON
do dashboard), e o resto é ajuste local. Se a API estiver atrás de proxy, o
`/metrics` precisa ser roteado como o resto.

## Coleta periódica

`GERENET_COLLECT_INTERVAL_MINUTES` (0 = desligado) liga a varredura; o worker
arma na subida, então mudar o valor pede restart do worker. Os números de cada
varredura estão no evento `collect.sweep` da auditoria. A wiki de equipamentos
tem as regras (idade, 2×, recusas).
