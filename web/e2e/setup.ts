// Seed do e2e (ciclo C2, Task 12) — roda como globalSetup, antes dos specs.
//
// Contrato (run-book e2e/README.md):
// - As variáveis do processo (GERENET_DATABASE_URL etc.) já devem estar no
//   ambiente do `npm run test:e2e`: o uvicorn do webServer, o CLI (execSync)
//   e o seed herdam o mesmo ambiente.
// - Usuários `admin` (`administrador`) e `e2e-aprovador` (`aprovador`):
//   verificados via `gerenet users list` (CLI) e criados SÓ se ausentes, com a
//   senha pipedada no stdin (o comando usa prompt oculto — nunca em argv). O
//   segredo vem de `E2E_PASSWORD` (default de fixture). O aprovador é distinto
//   do solicitante (spec §3.3) para o fumo de mudança (change.spec.ts).
// - Objetos do seed: API com X-Api-Key (settings.api_key). POSTs idempotentes
//   (201 → segue com o id do corpo; 409 → segue com o id achado na listagem).
import { execFileSync, execSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const BASE = "http://localhost:8000";
const API_KEY = process.env.GERENET_API_KEY ?? "dev-key-change-me";
const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";

// --- API ---------------------------------------------------------------------

async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<{ status: number; data: T | null; detail: string }> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      "x-api-key": API_KEY,
      ...init.headers,
    },
  });
  let corpo: T | null = null;
  let detail = "";
  try {
    corpo = (await res.json()) as T | null;
  } catch {
    /* sem corpo (204 etc.) */
  }
  if (typeof corpo === "object" && corpo !== null && "detail" in corpo) {
    detail = String((corpo as { detail: unknown }).detail ?? "");
  }
  return { status: res.status, data: corpo, detail };
}

interface Nomeado {
  id: number;
  name: string;
}

function idPorNome(items: Nomeado[] | null, nome: string, endpoint: string): number {
  const obj = items?.find((x) => x.name === nome);
  if (!obj) throw new Error(`GET ${endpoint} não devolveu o registro '${nome}'.`);
  return obj.id;
}

/** POST idempotente: 201 → id do corpo; 409 (já existe) → id da listagem. */
async function criarOuAchar(
  endpoint: string,
  nome: string,
  body: Record<string, unknown>,
): Promise<number> {
  const res = await api<Nomeado>(endpoint, { method: "POST", body: JSON.stringify(body) });
  if (res.status === 201 && res.data !== null) return res.data.id;
  if (res.status === 409) {
    const lista = await api<Nomeado[]>(endpoint);
    if (lista.status !== 200) {
      throw new Error(`GET ${endpoint} inesperado: ${lista.status} ${lista.detail}`);
    }
    return idPorNome(lista.data, nome, endpoint);
  }
  throw new Error(`POST ${endpoint} inesperado: ${res.status} ${res.detail}`);
}

// --- Usuários seed (CLI) ------------------------------------------------------

function usuarioExiste(nome: string): boolean {
  const stdout = execSync("uv run gerenet users list", { env: process.env, encoding: "utf8" });
  return stdout
    .split("\n")
    .map((linha) => linha.trim().split(/\s+/))
    .some((campos) => campos[1] === nome);
}

function criarUsuario(nome: string, role: string): void {
  execSync(`uv run gerenet users create ${nome} --role ${role}`, {
    input: `${SENHA}\n${SENHA}\n`,
    env: process.env,
    encoding: "utf8",
    stdio: ["pipe", "pipe", "pipe"],
  });
}

// --- Seed via API -------------------------------------------------------------

async function seed(): Promise<void> {
  const idSite = await criarOuAchar("/sites", "e2e-site-01", {
    name: "e2e-site-01",
    city: "São Paulo",
    uf: "SP",
  });
  const idEquip = await criarOuAchar("/devices", "ne8000-01", {
    name: "ne8000-01",
    management_address: "10.99.99.1",
    vendor: "huawei",
    model: "NE8000M12",
    family: "NE8000",
    role: "edge",
    site_id: idSite,
  });
  const idOrganizacao = await criarOuAchar("/organizations", "e2e-cliente-downstream", {
    name: "e2e-cliente-downstream",
    legal_name: "Cliente E2E Downstream Ltda",
    kind: "downstream",
    asn: 65001,
  });

  // Circuito — VLAN vive no CircuitCreate.vlan_mode (não há POST isolado de VLAN)
  const circ = await api("/circuits", {
    method: "POST",
    body: JSON.stringify({
      code: "e2e-circ-01",
      organization_id: idOrganizacao,
      site_id: idSite,
      access_device_id: idEquip,
      access_port: "GE0/0/1",
      edge_device_id: idEquip,
      stack: "ipv4",
      vlan_mode: "unica",
      p2p_v4_len: 31,
    }),
  });
  if (circ.status !== 201 && circ.status !== 409) {
    throw new Error(`POST /circuits inesperado: ${circ.status} ${circ.detail}`);
  }

  // Autorização de prefixo: checa antes de POSTar (a mesma org pode ter
  // prefixos sobrepostos na própria listagem, então o 409 não cobre duplicata)
  const listaAuth = await api<{ prefix: string }[]>(
    `/prefix-authorizations?organization_id=${idOrganizacao}&family=ipv4`,
  );
  if (listaAuth.status !== 200 || listaAuth.data === null) {
    throw new Error(
      `GET /prefix-authorizations inesperado: ${listaAuth.status} ${listaAuth.detail}`,
    );
  }
  if (!listaAuth.data.some((a) => a.prefix === "192.0.2.0/24")) {
    const auth = await api("/prefix-authorizations", {
      method: "POST",
      body: JSON.stringify({
        organization_id: idOrganizacao,
        family: "ipv4",
        prefix: "192.0.2.0/24",
      }),
    });
    if (auth.status !== 201 && auth.status !== 409) {
      throw new Error(`POST /prefix-authorizations inesperado: ${auth.status} ${auth.detail}`);
    }
  }

  // ---- Fase 5 — upstreams (§7): fixtures estáveis do fumo de upstream. ----
  // A organização operadora nasce AQUI via API (idempotente); a criação que
  // exercita a página (R-27) é do próprio fumo, com nome único por rodada.
  const idOperadora = await criarOuAchar("/organizations", "e2e-operadora-tier1", {
    name: "e2e-operadora-tier1",
    legal_name: "Operadora E2E Tier 1 Ltda",
    kind: "operadora",
    asn: 65110,
  });
  const idUpstream = await criarOuAchar("/upstreams", "e2e-upstream-tier1", {
    name: "e2e-upstream-tier1",
    tipo: "transito",
    priority: 1,
    organization_id: idOperadora,
    expected_prefixes_v4: 50000,
    expected_prefixes_v6: 2000,
  });

  // Circuito da operadora — SEM vínculo com o upstream (BR-1 §7): o fumo
  // liga os próprios circuitos por rodada e usa este como fixture estável.
  interface CircuitoSeed {
    id: number;
    code: string;
  }
  const circOperadora = await api<CircuitoSeed>("/circuits", {
    method: "POST",
    body: JSON.stringify({
      code: "e2e-circ-operadora-01",
      organization_id: idOperadora,
      site_id: idSite,
      access_device_id: idEquip,
      access_port: "GE0/0/13",
      edge_device_id: idEquip,
      stack: "ipv4",
      vlan_mode: "unica",
      p2p_v4_len: 31,
    }),
  });
  let idCircOperadora: number;
  if (circOperadora.status === 201 && circOperadora.data !== null) {
    idCircOperadora = circOperadora.data.id;
  } else if (circOperadora.status === 409) {
    const listaCircs = await api<CircuitoSeed[]>("/circuits");
    if (listaCircs.status !== 200) {
      throw new Error(`GET /circuits inesperado: ${listaCircs.status} ${listaCircs.detail}`);
    }
    const circ = listaCircs.data?.find((c) => c.code === "e2e-circ-operadora-01");
    if (!circ) {
      throw new Error("GET /circuits não devolveu o registro 'e2e-circ-operadora-01'.");
    }
    idCircOperadora = circ.id;
  } else {
    throw new Error(
      `POST /circuits (operadora) inesperado: ${circOperadora.status} ${circOperadora.detail}`,
    );
  }

  // Sessão BGP do circuito da operadora — checa antes de POSTar (o par
  // local/remoto é fixo; 409 não cobre reexecução, máquina de estados).
  const listaSessoes = await api<{ local_address: string }[]>(
    `/bgp-sessions?circuit_id=${idCircOperadora}`,
  );
  if (listaSessoes.status !== 200 || listaSessoes.data === null) {
    throw new Error(
      `GET /bgp-sessions inesperado: ${listaSessoes.status} ${listaSessoes.detail}`,
    );
  }
  if (!listaSessoes.data.some((s) => s.local_address === "10.99.128.1")) {
    const sess = await api("/bgp-sessions", {
      method: "POST",
      body: JSON.stringify({
        circuit_id: idCircOperadora,
        device_id: idEquip,
        afi: "ipv4",
        local_address: "10.99.128.1",
        remote_address: "10.99.128.2",
        asn_local: 64601,
        asn_remote: 65110,
        description: "sessão e2e — upstream tier1",
      }),
    });
    if (sess.status !== 201 && sess.status !== 409) {
      throw new Error(`POST /bgp-sessions (operadora) inesperado: ${sess.status} ${sess.detail}`);
    }
  }

  // Community de upstream (prepend, Região Sul) — checa pelo detalhe do
  // upstream (a UNIQUE (upstream_id, purpose, value, regiao) não é amigável
  // no 409; o padrão do prefix-authorization é mais claro).
  const detUpstream = await api<{
    comunidades: { purpose: string; value: string; regiao: string | null }[];
  }>(`/upstreams/${idUpstream}`);
  if (detUpstream.status !== 200 || detUpstream.data === null) {
    throw new Error(`GET /upstreams/${idUpstream} inesperado: ${detUpstream.status} ${detUpstream.detail}`);
  }
  if (!detUpstream.data.comunidades.some((c) => c.purpose === "prepend" && c.value === "65530:65400" && c.regiao === "sul")) {
    const comm = await api(`/upstreams/${idUpstream}/communities`, {
      method: "POST",
      body: JSON.stringify({
        purpose: "prepend",
        value: "65530:65400",
        direcao: "ambos",
        regiao: "sul",
        notes: "Community de teste e2e (prepend — Região Sul).",
      }),
    });
    if (comm.status !== 201 && comm.status !== 409) {
      throw new Error(
        `POST /upstreams/${idUpstream}/communities inesperado: ${comm.status} ${comm.detail}`,
      );
    }
  }

  // Equipamento do fumo da descoberta — SEPARADO do `ne8000-01` de propósito. A
  // adoção grava a sessão do enlace no equipamento DA PROPOSTA
  // (`adotar_proposta` → `create_session(device_id=proposta.device_id)`), e a
  // §14.1 admite uma única sessão ativa por (equipamento, VRF, família) — o
  // circuito da operadora acima já tem uma sessão ipv4 ativa no `ne8000-01` na
  // VRF pública. Com a proposta lida daquele equipamento, a adoção do fumo seria
  // recusada com 409 ("já existe sessão ipv4 ativa") e não haveria o que
  // exercitar. O nome evita o prefixo do outro (`/ne8000-01/` casa por substring
  // nas linhas das outras páginas).
  const idEquipDisco = await criarOuAchar("/devices", "ne8000-disco-01", {
    name: "ne8000-disco-01",
    management_address: "10.99.99.2",
    vendor: "huawei",
    model: "NE8000M12",
    family: "NE8000",
    role: "edge",
    site_id: idSite,
  });

  await seedDescoberta(idEquipDisco);
}

// --- Snapshot da descoberta (parte 2) -----------------------------------------
//
// A página **Migrar** não coleta nada: ela lê o `display current-configuration`
// que já está num snapshot. Sem esse snapshot o fumo da adoção não teria
// proposta nenhuma para adotar — e nenhuma API cria snapshot (quem coleta é o
// worker, de um equipamento de verdade). Então o seed escreve a configuração
// sintética e a linha de `device_snapshots` à mão, pelo mesmo `get_session()`
// do CLI, via `uv run python -c`.
//
// Os valores são por rodada (`Date.now()`): se o endereço do peer, o ASN ou o
// nome do cliente repetissem uma execução anterior, ou o peer já estaria na SoT
// (e não viraria proposta), ou a adoção esbarraria em `par_em_uso`/409 de nome
// repetido — nos dois casos o fumo ficaria sem o que adotar.

/** Raiz do repositório, achada de baixo para cima pelo `pyproject.toml`. O
 * globalSetup roda com o CWD em `web/` (o comando é `npm run test:e2e`), mas
 * não vale depender disso: o caminho gravado no snapshot é ABSOLUTO de
 * propósito — quem lê depois é a API, que roda na raiz. */
function raizDoRepo(): string {
  let dir = process.cwd();
  for (;;) {
    if (existsSync(join(dir, "pyproject.toml"))) return dir;
    const pai = dirname(dir);
    if (pai === dir) throw new Error("Raiz do repositório não encontrada (pyproject.toml).");
    dir = pai;
  }
}
const RAIZ = raizDoRepo();
const DIR_CONFIG = join(RAIZ, "data", "e2e");

/** O maior VID livre do site do equipamento.
 *
 * O VID do fumo vem da CONFIGURAÇÃO (é o que o equipamento tem), não do
 * alocador: com o VID já reservado no site, a proposta nasceria `nao_adotavel`
 * e não haveria o que adotar. O alocador first-fit dos circuitos cresce de 2
 * para cima, então o maior livre é o que a rodada não disputa com ele — nem com
 * as rodadas anteriores, que ficam reservadas no banco dedicado.
 */
const SCRIPT_VID_LIVRE = `
import json, sys
from sqlalchemy import select
from gerenet.db import get_session
from gerenet.domain import models
with get_session() as session:
    device = session.get(models.Device, int(sys.argv[1]))
    if device is None:
        raise SystemExit("equipamento do seed nao encontrado")
    site_id = device.site_id
    tomados = set(session.scalars(select(models.Vlan.vid).where(
        models.Vlan.site_id == site_id,
        models.Vlan.device_id.is_(None),
        models.Vlan.status == "reservada",
    )))
livre = next(v for v in range(4094, 1, -1) if v not in tomados)
print(json.dumps({"vid": livre, "site_id": site_id}))
`;

/** A linha de `device_snapshots` que aponta para a configuração escrita. */
const SCRIPT_SNAPSHOT = `
import sys
from datetime import datetime, timezone
from gerenet.db import get_session
from gerenet.domain import models
with get_session() as session:
    snap = models.DeviceSnapshot(
        device_id=int(sys.argv[1]),
        status="success",
        finished_at=datetime.now(timezone.utc),
        resources={},
        errors={},
        raw_files={"config_backup": [sys.argv[2]]},
        duration_ms=0,
    )
    session.add(snap)
    session.flush()
    print(snap.id)
`;

/** Roda um script de seed do banco pelo mesmo `uv run` do CLI.
 *
 * `execFileSync` com a lista de argumentos, e não `execSync` com uma linha de
 * shell: o script é multi-linha e tem aspas — numa linha de shell ele seria
 * remontado, e o caminho da configuração viraria sintaxe do Python. */
function python(args: string[]): string {
  return execFileSync("uv", ["run", "python", "-c", ...args], {
    env: process.env,
    encoding: "utf8",
  });
}

/** A configuração sintética da rodada: a forma do `display
 * current-configuration` com UM enlace que a SoT ainda não conhece
 * (subinterface com `vlan-type`/`ip address` + o peer BGP dela). Ela não vem de
 * equipamento nenhum, e é a única fonte de proposta do fumo.
 *
 * A `description` da subinterface é de propósito e FORA do formato do §4
 * (`<CÓDIGO> <ORG> [<VELOCIDADE>]`): desde a frente da velocidade a SoT gerencia
 * a linha, então a diferença cai no grupo que gateia e é ela que faz a revisão
 * exigir o `ciente`. O grupo "a SoT não gerencia" (só o `mtu`) sai vazio — o
 * seed não escreve `mtu` nenhum. */
function configDoEnlace(v: {
  vid: number;
  cliente: string;
  ipLocal: string;
  ipRemoto: string;
  asn: number;
}): string {
  return `#
# Configuração SINTÉTICA do fumo de descoberta (web/e2e/setup.ts) — imita a
# forma do \`display current-configuration\` e não vem de equipamento nenhum.
#
sysname NE8000-E2E
#
interface Eth-Trunk127.${v.vid}
 vlan-type dot1q ${v.vid}
 description ${v.cliente}
 ip address ${v.ipLocal} 255.255.255.254
#
bgp 64601
 peer ${v.ipRemoto} as-number ${v.asn}
 peer ${v.ipRemoto} description ${v.cliente}
 ipv4-family unicast
  peer ${v.ipRemoto} enable
#
return
`;
}

/** Desativa as sessões ativas do equipamento do fumo da descoberta.
 *
 * A adoção de cada rodada grava UMA sessão na SoT, e a §14.1 admite uma única
 * sessão ativa por (equipamento, VRF, família): na rodada seguinte a adoção
 * bateria na sessão ativa da rodada anterior e o fumo morreria com 409 — um
 * e2e que só passa em banco limpo não serve. Desativar é o caminho da operação
 * para tirar uma sessão de cena (sessão não se exclui), e o circuito da rodada
 * anterior fica como ficou.
 */
async function desativarSessoesDoFumo(deviceId: number): Promise<void> {
  // O default da listagem já é `include_disabled=false`: só as ativas voltam.
  const lista = await api<{ id: number }[]>(`/bgp-sessions?device_id=${deviceId}`);
  if (lista.status !== 200 || lista.data === null) {
    throw new Error(
      `GET /bgp-sessions (equipamento do fumo) inesperado: ${lista.status} ${lista.detail}`,
    );
  }
  for (const sessao of lista.data) {
    const desativada = await api(`/bgp-sessions/${sessao.id}`, {
      method: "PATCH",
      body: JSON.stringify({ admin_status: false }),
    });
    if (desativada.status !== 200) {
      throw new Error(
        `PATCH /bgp-sessions/${sessao.id} inesperado: ${desativada.status} ${desativada.detail}`,
      );
    }
  }
}

async function seedDescoberta(deviceId: number): Promise<void> {
  await desativarSessoesDoFumo(deviceId);
  const n = Date.now();
  // O par p2p dentro do bloco privado do IPAM (`100.64.0.0/10`), lá em cima: o
  // alocador first-fit anda de baixo para cima e não chega perto, e os bits
  // baixos do relógio fazem o par (e o peer) serem novos a cada rodada.
  const o2 = 64 + ((n >>> 16) & 0x3f);
  const o3 = (n >>> 8) & 0xff;
  const o4 = n & 0xfe;
  const ipLocal = `100.${o2}.${o3}.${o4}`;
  const ipRemoto = `100.${o2}.${o3}.${o4 + 1}`;
  // ASN de 32 bits fora das faixas reservadas (os 4 bi) e sem organização
  // cadastrada: é o que faz a revisão exercitar o caminho "Criar a nova".
  const asn = 4_000_000_000 + (n % 100_000_000);
  // O nome do cliente vira a descrição do peer E o nome da organização nova.
  const cliente = `CLIENTE-E2E-${n}`;

  const saida = python([SCRIPT_VID_LIVRE, String(deviceId)]);
  const { vid } = JSON.parse(saida.trim()) as { vid: number };

  mkdirSync(DIR_CONFIG, { recursive: true });
  const arquivo = join(DIR_CONFIG, `discovery-${n}.txt`);
  writeFileSync(arquivo, configDoEnlace({ vid, cliente, ipLocal, ipRemoto, asn }), "utf8");
  const snapshotId = python([SCRIPT_SNAPSHOT, String(deviceId), arquivo]).trim();

  console.log(
    `[seed] descoberta: snapshot ${snapshotId}, VLAN ${vid}, peer ${ipRemoto} AS${asn} (${arquivo})`,
  );
}

// --- globalSetup ---------------------------------------------------------------

export default async function globalSetup(): Promise<void> {
  if (!usuarioExiste("admin")) {
    criarUsuario("admin", "administrador");
  }
  // Aprovador distinto do solicitante — o fumo de mudança (change.spec.ts)
  // solicita como admin e aprova como e2e-aprovador (spec §3.3: não aprovar o
  // próprio pedido).
  if (!usuarioExiste("e2e-aprovador")) {
    criarUsuario("e2e-aprovador", "aprovador");
  }
  await seed();
}
