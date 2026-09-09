---
title: Preparação para a coleta: Vault e host keys
secao: Começando
secao_order: 1
order: 4
---

# Preparação para a coleta: Vault e host keys

Cadastrar o equipamento na web é parte do caminho. Para a coleta conectar por
SSH, duas coisas ainda precisam estar prontas: a credencial da conta de
automação (no Vault, com o grupo `automacao` no Source of Truth) e a host key do
equipamento (fingerprint registrada). As duas são configuradas por CLI; o
formulário web não tem campos para elas.

## Credencial da conta de automação: `gerenet vault seed`

O worker loga nos equipamentos com a conta de automação (por padrão,
`gerenet-auto`). O comando `gerenet vault seed` faz duas coisas:

1. Grava `username` e `password` no Vault KV v2, no caminho lógico
   `gerenet/credential-groups/automacao` (no dev, o mount `secret/` resolve para
   `secret/data/gerenet/credential-groups/automacao`).
2. Garante o grupo `automacao` no Source of Truth apontando para esse caminho.
   É esse grupo que o cadastro do equipamento referencia, e a senha nunca é
   digitada no formulário.

```bash
gerenet vault seed                              # prompt de senha oculta
gerenet vault seed --username gerenet-auto      # outra conta de automação
```

A senha é pedida em prompt oculto, nunca em argumento de linha de comando. O
comando é idempotente: re-executar apenas reescreve o segredo e mantém o grupo.

Requisitos: o Vault no ar (no dev, `docker compose up -d` sobe o serviço) e as
variáveis `GERENET_VAULT_URL` (dev: `http://localhost:8200`) e
`GERENET_VAULT_TOKEN` (dev: `gerenet-dev-root`), definidas no `.env`. No compose
dev, o boot já grava essa credencial a partir de `GERENET_VAULT_USERNAME` e
`GERENET_VAULT_PASSWORD`; o seed manual serve para trocar a senha ou rodar
fora do compose.

Para grupos além de `automacao`, o segredo vai ao Vault à parte (via API de
grupos de credencial) e o grupo no Source of Truth é registrado com
`gerenet credential-groups create --vault-path <caminho>`.

## Host key: `gerenet hostkey register`

Antes de executar qualquer comando, a conexão confere o fingerprint da chave
do servidor SSH (proteção contra MITM). Sem fingerprint registrada, a coleta
falha com `HostKeyMismatch` e a mensagem manda registrar antes de coletar. Se a
chave recebida não confere, a conexão é recusada, a mensagem traz o fingerprint
recebido e orienta a registrar o correto com `gerenet hostkey register`.

Para registrar:

1. Obtenha o fingerprint pela rede de gerência:

   ```bash
   ssh-keyscan -T 10 -t rsa,ecdsa,ed25519 <ip-de-gerencia> 2>/dev/null | ssh-keygen -lf -
   ```

   A saída lista linhas como `256 SHA256:5Vj... (ED25519)`. Copie apenas o
   `SHA256:5Vj...`.

2. Registre no Source of Truth. O argumento aceita ID ou nome do equipamento:

   ```bash
   gerenet hostkey register <id|nome> SHA256:5Vj...
   ```

Na interface web, o mesmo registro é feito no modal de edição do equipamento:
o botão "Gerar fingerprint" lê a chave pela rede de gerência (sem usar
credencial) e preenche o campo; ao salvar, o fingerprint é registrado com a
mesma auditoria `hostkey.register`. O valor pode ser ajustado à mão antes de
salvar, como no CLI.

O fingerprint fica em `devices.host_key_fingerprint` e o registro gera o evento
de auditoria `hostkey.register`. A comparação normaliza o esquema para
minúsculas e ignora o padding `=` no final: o servidor calcula o hash com
padding e o `ssh-keygen -lf` imprime sem, então a mesma chave compare igual nos
dois lados.

Se a coleta falhar com `Host key ... não confere`, a chave do servidor mudou
desde o registro. Confirme a troca por outro canal (console do equipamento,
outro operador) antes de re-registrar: chave nova pode ser manutenção
legítima ou um adversário no meio do caminho.

## Depois: a coleta

Com credencial e host key prontas, o ciclo é o de sempre: equipamento cadastrado
na web com o grupo `automacao` no campo de credenciais, e coleta iniciada por
"Coletar agora" na lista de equipamentos ou por:

```bash
gerenet collect run --device <id|nome>
```

Veja [Equipamentos, coleta e snapshots](/wiki/equipamentos) para o que a coleta
faz e o que cada estado de job significa.
