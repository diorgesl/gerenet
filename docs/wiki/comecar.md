---
title: Primeiros passos: login, perfis e primeiro equipamento
secao: Começando
order: 2
---

# Primeiros passos: login, perfis e primeiro equipamento

## Login

A interface web é acessada pela rota `/` e usa usuário e senha. A sessão é um
cookie (`gerenet_sess`, HttpOnly e SameSite=Lax); em produção sob HTTPS, o
cookie é marcado como seguro.

O primeiro usuário é criado pelo administrador pela linha de comando
(veja `README.md`):

```bash
gerenet users create admin --role administrador
```

A senha é pedida em prompt interativo (nunca em argumento da linha de comando).
Para CLI e automações existe também a API key (`X-Api-Key`), separada do login
da interface.

Se o login falhar 5 vezes consecutivas para o mesmo IP + usuário, o acesso é
bloqueado temporariamente (erro 429 com `Retry-After`). Se o Redis estiver
fora do ar, o bloqueio é ignorado (fail-open) para não derrubar o login.

## Perfis de acesso

| Perfil | O que pode fazer |
|---|---|
| Visualizador | Consultar inventário, serviços e estado |
| Operador | Cadastrar objetos e gerar planos |
| Aprovador | Aprovar ou rejeitar mudanças |
| Executor | Executar mudanças aprovadas |
| Administrador | Gerenciar usuários, templates e políticas globais |

Na prática, hoje o fluxo concentra-se em **cadastro e consulta**: o operador
cadastra sites, equipamentos, organizações, circuitos, sessões BGP e
autorizações. A aprovação e a execução de mudanças fazem parte do fluxo de
[mudanças controladas](/wiki/mudancas-controladas), ainda em planejamento.

## Passo a passo: primeiro equipamento

1. **Crie um Site (POP)** — nome, cidade/UF, bloco de enlaces p2p IPv4
   (padrão `100.64.0.0/10`) e base IPv6 do POP (ex.: `2804:194C:1000::/48`).
2. **Crie o grupo de credenciais no Vault** (somente CLI):
   `gerenet credential-groups create` — o grupo referencia o segredo; a senha
   nunca é digitada no formulário do equipamento.
3. **Cadastre o equipamento** — nome único, endereço de gerência, porta SSH,
   modelo/família, função, site, ASN local e o grupo de credenciais. Se quiser
   validar a chave SSH do host, registre a fingerprint com
   `gerenet hostkey register <equipamento> <fingerprint>`.
4. **Rode a primeira coleta** — na lista de [Equipamentos](/wiki/equipamentos),
   botão "Coletar agora", ou pela CLI:
   `gerenet collect run --device <id|nome>` (ou `--all`). A coleta vai para a
   fila de jobs; um job por equipamento, com lock garantindo uma coleta por vez.
5. **Acompanhe o job** — o registro aparece na tela Jobs como `running` assim
   que o worker executa (enquanto o job está na fila do RQ ele ainda não existe
   no banco) e termina em `success`, `partial` ou `error`; em `error`, o motivo
   aparece na coluna Motivo.
6. **Veja o snapshot** — o resultado estruturado da coleta (recursos coletados
   e erros por recurso) está na página Snapshots; os backups brutos dos
   comandos ficam guardados por coleta.

Depois do ciclo completo, a página [Reconciliação](/wiki/operacao) mostra o
desejado × encontrado para o equipamento, ainda que nada tenha sido aplicado.

## Credenciais: onde elas vivem

- As credenciais dos equipamentos **nunca** são cadastradas no formulário de
  equipamento: o cadastro apenas referencia um **grupo de credenciais**.
- O grupo aponta para o segredo no Vault, lido somente na hora da coleta.
- Em logs, snapshots e auditoria, senha, segredo, token e afins são mascarados
  (aparecem como `[mascarado]`).

Siga o passo a passo de [Equipamentos, coleta e snapshots](/wiki/equipamentos)
para entender cada campo e o que a coleta realmente faz.
