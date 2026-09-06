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
