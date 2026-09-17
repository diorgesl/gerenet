import { useMemo } from "react";
import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { usePlano, usePlanoValidacao } from "@/api/hooks";
import { ApiError } from "@/api/client";
import type { AchadoOut, ClassePlanoOut } from "@/api/types";

// Os quatro papéis de portão (§5/§11) — espelha models.GATE_PAPEL. A matriz tem
// coluna fixa: papel sem portão nenhum é "não mencionada", e não uma coluna que
// some quando o plano não o usa.
const PAPEIS = ["upstream", "cdn", "parceiro", "ix"] as const;

const SEVERIDADE_ORDEM: Record<string, number> = { critico: 0, atencao: 1, informativo: 2 };

/** O que os portões de um papel dizem sobre a classe: aceita, recusa ou não
 * menciona. Um papel pode ter mais de um portão (IPv4 e IPv6, por exemplo) —
 * daí o `some`, e não a leitura do primeiro. */
function celulaDaMatriz(classe: ClassePlanoOut, papel: string, portoes: { papel: string; aceitas: string[]; recusadas: string[] }[]) {
  const doPapel = portoes.filter((p) => p.papel === papel);
  if (doPapel.some((p) => p.aceitas.includes(classe.nome))) return "anunciada";
  if (doPapel.some((p) => p.recusadas.includes(classe.nome))) return "recusada";
  return "não mencionada";
}

export default function CommunitiesPlan() {
  const plano = usePlano();
  const validacao = usePlanoValidacao();
  const dados = plano.data;
  const achados = useMemo(
    () => [...(validacao.data ?? [])].sort((a, b) => (SEVERIDADE_ORDEM[a.severidade] ?? 9) - (SEVERIDADE_ORDEM[b.severidade] ?? 9)),
    [validacao.data],
  );

  if (plano.isLoading) return <main><p aria-busy="true">Carregando…</p></main>;
  if (plano.error) {
    return <main><PageHeader titulo="Comunidades · Plano" /><p role="alert">{plano.error instanceof ApiError ? plano.error.message : "Falha ao carregar o plano."}</p></main>;
  }
  if (!dados || (!dados.classes.length && !dados.instrucoes.length)) {
    return (
      <main>
        <PageHeader titulo="Comunidades · Plano" />
        <p>
          Nenhum plano adotado ainda. O plano vem da configuração já coletada, pelo
          <code>gerenet communities plan adotar</code> ou pelo <code>POST /api/v1/communities/plan/adopt</code>.
        </p>
      </main>
    );
  }

  const portoes = dados.portoes;
  // Quem testa e quem aplica saem do plano já contados pelo serviço: a leitura
  // da configuração resolve o corpo das definições citadas, então a route-policy
  // que cita uma classe usa o valor dela. A coluna sem uso é "ninguém" — que é o
  // caso das classes de vocabulário (`blackhole`, `no-export`, `no-advertise`),
  // sem valor e sem uso, e que a página mostra assim mesmo: esconder as três
  // seria decidir o que o plano não decidiu.
  const testes = new Set(dados.classes.flatMap((c) => (c.testam.length ? [c.nome] : [])));
  const aplicadas = new Set(dados.classes.flatMap((c) => (c.aplicam.length ? [c.nome] : [])));

  return (
    <main>
      <PageHeader titulo="Comunidades · Plano" />
      <section aria-labelledby="plano-cabecalho">
        <h2 id="plano-cabecalho">Cabeçalho</h2>
        <p><strong>ASN principal:</strong> {dados.asn_principal ?? "—"}</p>
        <p><strong>ASNs anunciados:</strong> {dados.asns_anunciados.map((a) => String(a.asn)).join(", ") || "—"}</p>
        <p><strong>Origem:</strong> {dados.observacoes ?? "—"}</p>
      </section>

      <section aria-labelledby="plano-classes">
        <h2 id="plano-classes">Classes e instruções</h2>
        <DataTable<ClassePlanoOut>
          colunas={[
            { key: "nome", title: "Nome" },
            { key: "banda", title: "Banda", render: (c) => c.banda ?? "—" },
            { key: "valor_v4", title: "v4", render: (c) => c.valor_v4 ?? "—" },
            { key: "valor_v6", title: "v6", render: (c) => c.valor_v6 ?? "—" },
            { key: "aplicam", title: "Quem aplica", render: (c) => c.aplicam.join(", ") || "ninguém" },
            { key: "testam", title: "Quem testa", render: (c) => c.testam.join(", ") || "ninguém" },
            {
              key: "selo",
              title: "Situação",
              render: (c) =>
                aplicadas.has(c.nome) && !testes.has(c.nome) ? (
                  <span className="badge badge-fail">aplicada e não testada</span>
                ) : testes.has(c.nome) && !aplicadas.has(c.nome) ? (
                  <span className="badge badge-warn">testada e não aplicada</span>
                ) : (
                  "—"
                ),
            },
          ]}
          linhas={dados.classes}
        />
        {/* As duas contagens abaixo e o painel de divergências contam a MESMA
            configuração em granularidades diferentes, e por isso podem parecer
            se contradizer sobre a mesma classe: aqui o uso é por CÓDIGO (o corpo
            da definição citada resolve o valor), lá o achado aponta a linha pelo
            VALOR LITERAL que ela escreveu. */}
        <p>
          "Quem aplica" e "quem testa" contam o uso por <strong>código</strong> de classe: a
          definição citada entra pelo corpo dela, então a route-policy que cita uma classe
          aplica ou testa o valor dela. O painel de divergências, mais abaixo, aponta a linha
          da configuração pelo <strong>valor literal</strong> — a mesma classe pode aparecer
          com quem a testa aqui e ainda assim vir de lá como aplicada e não testada, sem que
          nenhuma das duas leituras esteja errada.
        </p>
      </section>

      <section aria-labelledby="plano-matriz">
        <h2 id="plano-matriz">Matriz classe × papel</h2>
        <table aria-label="matriz classe × papel">
          <thead>
            <tr>
              <th>Classe</th>
              {PAPEIS.map((p) => <th key={p}>{p}</th>)}
            </tr>
          </thead>
          <tbody>
            {dados.classes.map((classe) => (
              <tr key={classe.nome}>
                <td>{classe.nome}</td>
                {PAPEIS.map((papel) => (
                  <td key={papel}>{celulaDaMatriz(classe, papel, portoes)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p>Portões: {portoes.map((p) => p.nome).join(", ") || "nenhum"}.</p>
      </section>

      <section aria-labelledby="plano-alvos">
        <h2 id="plano-alvos">Alvos</h2>
        <DataTable
          colunas={[
            { key: "nome", title: "Grupo" },
            { key: "papel", title: "Papel" },
            { key: "codigo_v4", title: "Código v4", render: (a) => a.codigo_v4 ?? "—" },
            { key: "codigo_v6", title: "Código v6", render: (a) => a.codigo_v6 ?? "—" },
            { key: "gate_nome", title: "Portão", render: (a) => a.gate_nome ?? "—" },
            { key: "estado", title: "Sessão", render: (a) => a.estado },
          ]}
          linhas={dados.alvos}
        />
      </section>

      <section aria-labelledby="plano-divergencias">
        {/* A contagem sai da resposta, e não de `achados` (que é `[]` sem ela):
            em voo ou com a leitura falha o painel não pode dizer "0" nem
            "nenhuma divergência" — quem não mediu não tem o que afirmar. O
            título segue o MESMO sinal do corpo (`isError` zera o número): um
            refetch que falha depois de uma carga boa deixa `data` velho no
            cache, e sem isso o título contaria o que o alerta abaixo nega. */}
        <h2 id="plano-divergencias">
          Divergências{!validacao.isError && validacao.data ? ` (${achados.length})` : ""}
        </h2>
        <DataTable<AchadoOut>
          colunas={[
            { key: "severidade", title: "Severidade" },
            { key: "descricao", title: "Achado" },
            { key: "filtro", title: "Filtro", render: (a) => a.filtro ?? "—" },
            { key: "linha", title: "Linha", render: (a) => a.linha ?? "—" },
            { key: "acao", title: "Ação sugerida", render: (a) => a.acao ?? "—" },
          ]}
          linhas={achados}
          carregando={validacao.isLoading}
          erro={
            validacao.isError
              ? "Não foi possível ler a validação do plano; nada foi comparado com a configuração."
              : undefined
          }
          vazio="Nenhuma divergência entre o plano e a configuração."
        />
      </section>
    </main>
  );
}
