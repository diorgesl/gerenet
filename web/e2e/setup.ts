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
import { execSync } from "node:child_process";

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
