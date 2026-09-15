# Runbook: deploy de produção

Instalação do gerenet num servidor, com o compose de produção
(`compose.prod.example.yaml`) e a entrada pelo Traefik. Vale para a primeira
subida e para as atualizações.

O que este documento **não** cobre: validar a automação contra equipamento real
(veja `runbook-validacao-ne8000.md`, `runbook-validacao-switch-mpls.md` e
`runbook-validacao-upstream.md`) e observabilidade (veja
`runbook-observabilidade.md`).

## Pré-requisitos

- Docker com o plugin `compose` no servidor;
- Traefik já rodando, com a rede `traefik-public` (externa), os entrypoints
  `http` e `https` e um certresolver. O exemplo usa `le` (Let's Encrypt), o que
  exige o domínio resolvendo para este servidor e a porta 80 alcançável da
  internet para o desafio do certificado;
- um domínio para a interface (ex.: `gerenet.exemplo.com.br`).

## 1. Diretório e arquivos

O `build:` do compose usa o próprio diretório como contexto, então o deploy é um
checkout do repositório:

```bash
git clone <url-do-repo> /opt/gerenet
cd /opt/gerenet
cp compose.prod.example.yaml compose.yaml
cp .env.prod.example .env && chmod 600 .env
```

Preencha o `.env` (domínio, `STACK_NAME` único no host, senhas e tokens). As
variáveis com `?` no compose são obrigatórias: faltando alguma, o
`docker compose` recusa subir em vez de usar um valor fraco em silêncio. Para a
senha do Postgres, `openssl rand -base64 32` serve.

O diretório dos brutos da coleta é o único caminho do host montado nos
containers, e a imagem de produção roda como uid 1000:

```bash
mkdir -p data/backups
sudo chown -R 1000:1000 data
```

## 2. Subir a stack

```bash
docker compose up -d --build
docker compose ps
```

A `api` aplica as migrações na subida (entrypoint, `alembic upgrade head`) e só
então serve. O Vault sobe **selado**: a api e o worker funcionam, mas a coleta
falha até o passo 3. O cliente do Vault é criado na hora do uso, não no boot,
então a api não fica em restart-loop por causa disso.

## 3. Vault: init, unseal e token de serviço

O Vault de produção tem storage em arquivo e nasce selado. Guarde as chaves de
unseal e o root token no cofre da equipe, **fora** do servidor.

```bash
cd /opt/gerenet
docker compose exec vault vault operator init        # 5 chaves + root token

# repita com 3 das 5 chaves
docker compose exec vault vault operator unseal
docker compose exec vault vault operator unseal
docker compose exec vault vault operator unseal
```

Com o root token, crie a policy da aplicação (só o caminho `gerenet/*`) e um
token de serviço. O `read -rs` evita deixar o root token no histórico do shell:

```bash
read -rs VAULT_ROOT_TOKEN   # cole o root token e dê Enter

# O Vault de servidor nasce sem motor de segredos; o `-dev` do compose de
# desenvolvimento monta um KV v2 em `secret/` sozinho, e é esse caminho que a
# aplicação usa. Sem este passo, o `gerenet vault seed` do passo 4 responde
# `no handler for route "secret/data/gerenet/..."`.
docker compose exec -T -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" vault \
  vault secrets enable -path=secret -version=2 kv

docker compose exec -T -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" vault \
  vault policy write gerenet - <<'HCL'
path "secret/data/gerenet/*" {
  capabilities = ["create", "read", "update"]
}
path "secret/metadata/gerenet/*" {
  capabilities = ["read", "list"]
}
HCL

docker compose exec -T -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" vault \
  vault token create -policy=gerenet -period=768h -display-name=gerenet
```

Copie o token devolvido para `GERENET_VAULT_TOKEN` no `.env` e recrie a api e o
worker:

```bash
docker compose up -d api worker
```

Depois de cada restart do host, o container do Vault volta **selado** e precisa
dos mesmos 3 unseals. Enquanto ele estiver selado, a coleta falha e gravar senha
de sessão BGP responde 503 (o resto da interface funciona). As chaves de unseal
precisam estar acessíveis a quem opera o servidor, no cofre da equipe e não no
host.

O token é periódico (768 h) e **precisa ser renovado antes de vencer**, senão a
coleta para. Renove pelo próprio token, que tem permissão de self-renew:

```cron
# renova todo dia 1, às 03:17
17 3 1 * * cd /opt/gerenet && . ./.env && docker compose exec -T -e VAULT_TOKEN="$GERENET_VAULT_TOKEN" vault vault token renew >> /var/log/gerenet-vault-renew.log 2>&1
```

## 4. Credencial de coleta e usuário admin

A conta de automação é a que faz SSH nos equipamentos. Ela vai para o Vault, e o
`seed` também garante o grupo `automacao` na base (é o grupo que os
equipamentos referenciam):

```bash
docker compose exec api gerenet vault seed      # pede usuário e senha
docker compose exec api gerenet users create admin --role administrador
```

As duas senhas são pedidas por prompt oculto, nunca em argumento de comando.

## 5. Conferir que subiu

```bash
docker compose ps
curl -sS https://gerenet.exemplo.com.br/healthz     # {"status":"ok"}
docker compose logs --tail 50 api worker
```

Depois, no navegador: login em `https://gerenet.exemplo.com.br`, cadastro do
equipamento e uma coleta de teste (a primeira coleta só passa com o passo 4
feito). A validação contra equipamento real é a dos runbooks de validação.

## 6. Atualizar a instalação

```bash
cd /opt/gerenet
git pull
docker compose up -d --build
```

A migração roda na subida da api. O `docker compose up -d` recria só o que
mudou; a api fica fora do ar durante a troca do container (segundos).

## 7. Backup

- **Configurações coletadas e backups pré-mudança**: `data/backups/` no host.
  É evidência de mudança, então vale copiar para fora do servidor.
- **Banco**:
  `docker compose exec -T db pg_dump -U gerenet gerenet | gzip > /var/backups/gerenet-$(date +%F).sql.gz`
- **Vault**: os segredos ficam no volume `vault-data`. Se ele se perder, a
  credencial de automação pode ser regravada com `gerenet vault seed` (é um
  segredo só), mas o token de serviço precisa ser criado de novo (passo 3) e o
  `.env` atualizado.

## 8. Notas de operação

- O Vault não publica porta. Tudo que se faz nele é por
  `docker compose exec vault vault ...`.
- Se o host não permitir `IPC_LOCK`, troque `"disable_mlock": false` por `true`
  no `VAULT_LOCAL_CONFIG` e remova o `cap_add` do serviço. O Vault passa a
  avisar sobre memória não travada e continua funcionando.
- O exemplo redireciona HTTP para HTTPS (middleware nas duas últimas labels do
  serviço `api`). Para servir as duas pontas, apague as duas.
- O `/metrics` responde na rede interna e aceita `GERENET_METRICS_TOKEN`
  (Bearer). Este compose não sobe Prometheus nem Grafana: aponte o monitoramento
  que já roda no servidor para o endpoint e importe o painel
  `gerenet — operação` (`docker/observability/grafana/dashboards/gerenet.json`)
  no Grafana que já existe. (O compose de desenvolvimento é que traz um
  Prometheus, e um Grafana opcional.)
- O `.env` fica com `chmod 600`. Ele tem o token do Vault e a chave da API, e é
  o único lugar com segredo fora do Vault.
