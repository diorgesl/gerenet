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

São duas edições, com o mesmo valor:

1. a variável `GERENET_METRICS_TOKEN` no serviço `api` do `compose.yaml` (ou no
   ambiente da plataforma, em produção);
2. o bloco `authorization` no job do `docker/observability/prometheus.yml`:

```yaml
  - job_name: gerenet
    metrics_path: /metrics
    authorization:
      credentials: <mesmo-token>
    static_configs:
      - targets: ["api:8000"]
```

Não use `${GERENET_METRICS_TOKEN:-}` no compose para preencher o valor: sem a
variável no ambiente, o default vazio derruba a API na subida, porque o
`Settings` recusa token vazio de propósito (é o que impede "token vazio = endpoint
aberto"). Para manter o endpoint sem autenticação, deixe a variável ausente.

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
