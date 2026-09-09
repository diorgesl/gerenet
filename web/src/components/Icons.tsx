import type { ReactNode } from "react";

/* Ícones de navegação — linha fina (traço 1.8) no espírito Lucide, 17px.
   Sem dependência externa: SVGs inline, aria-hidden (decorativos: o rótulo
   sempre acompanha). Paths inspirados em Lucide (MIT), simplificados. */

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      className="nav-icone"
      width={17}
      height={17}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const R = (d: string) => <path d={d} />;
const C = (cx: number, cy: number, r: number) => <circle cx={cx} cy={cy} r={r} />;
const L = (x1: number, y1: number, x2: number, y2: number) => <line x1={x1} y1={y1} x2={x2} y2={y2} />;

/** Ícones por rota do menu — a mesma chave de `GRUPOS_NAV`/pins. */
export const ICONES_NAV: Record<string, ReactNode> = {
  // Visão
  "/": (
    <Svg>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </Svg>
  ),
  // Infraestrutura
  "/devices": (
    <Svg>
      <rect x="2" y="2" width="20" height="8" rx="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" />
      {L(6, 6, 6.01, 6)}
      {L(6, 18, 6.01, 18)}
    </Svg>
  ),
  "/sites": (
    <Svg>
      {R("M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z")}
      {C(12, 10, 3)}
    </Svg>
  ),
  "/circuits": (
    <Svg>
      {C(12, 4.5, 2.2)}
      {C(4.5, 19.5, 2.2)}
      {C(19.5, 19.5, 2.2)}
      {R("M11 6.5 5.6 17.6")}
      {R("M13 6.5 18.4 17.6")}
    </Svg>
  ),
  // Roteamento
  "/upstreams": (
    <Svg>
      {C(12, 12, 10)}
      {R("M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20")}
      {R("M2 12h20")}
    </Svg>
  ),
  "/bgp-sessions": (
    <Svg>
      {R("m17 2 4 4-4 4")}
      {R("M3 11v-1a4 4 0 0 1 4-4h14")}
      {R("m7 22-4-4 4-4")}
      {R("M21 13v1a4 4 0 0 1-4 4H3")}
    </Svg>
  ),
  "/prefix-authorizations": (
    <Svg>
      {R("M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1 1 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z")}
      {R("m9 12 2 2 4-4")}
    </Svg>
  ),
  "/policy-profiles": (
    <Svg>
      {L(21, 4, 14, 4)}
      {L(10, 4, 3, 4)}
      {L(21, 12, 12, 12)}
      {L(8, 12, 3, 12)}
      {L(21, 20, 16, 20)}
      {L(12, 20, 3, 20)}
      {L(14, 2, 14, 6)}
      {L(8, 10, 8, 14)}
      {L(16, 18, 16, 22)}
    </Svg>
  ),
  "/communities": (
    <Svg>
      {R("M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z")}
      {C(7.5, 7.5, 0.5, )}
    </Svg>
  ),
  // MPLS
  "/mpls/domains": (
    <Svg>
      <rect x="16" y="16" width="6" height="6" rx="1" />
      <rect x="2" y="16" width="6" height="6" rx="1" />
      <rect x="9" y="2" width="6" height="6" rx="1" />
      {R("M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3")}
      {R("M12 12V8")}
    </Svg>
  ),
  "/mpls/l2vc": (
    <Svg>
      {R("M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71")}
      {R("M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71")}
    </Svg>
  ),
  "/mpls/vsi": (
    <Svg>
      <rect x="3" y="3" width="8" height="8" rx="2" />
      {R("M7 11v4a2 2 0 0 0 2 2h4")}
      <rect x="13" y="13" width="8" height="8" rx="2" />
    </Svg>
  ),
  // Operação
  "/change-requests": (
    <Svg>
      {C(18, 18, 3)}
      {C(6, 6, 3)}
      {R("M13 6h3a2 2 0 0 1 2 2v7")}
      {R("M11 18H8a2 2 0 0 1-2-2V9")}
    </Svg>
  ),
  "/snapshots": (
    <Svg>
      {R("M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z")}
      {C(12, 13, 3)}
    </Svg>
  ),
  "/desired-config": (
    <Svg>
      {R("M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z")}
      {R("M14 2v4a2 2 0 0 0 2 2h4")}
      {R("m10 13-2 2 2 2")}
      {R("m14 17 2-2-2-2")}
    </Svg>
  ),
  "/reconcile": (
    <Svg>
      {R("M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8")}
      {R("M21 3v5h-5")}
      {R("M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16")}
      {R("M8 16H3v5")}
    </Svg>
  ),
  "/jobs": (
    <Svg>
      {R("m3 17 2 2 4-4")}
      {R("m3 7 2 2 4-4")}
      {L(13, 6, 21, 6)}
      {L(13, 12, 21, 12)}
      {L(13, 18, 21, 18)}
    </Svg>
  ),
  // Gestão
  "/organizations": (
    <Svg>
      {R("M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z")}
      {R("M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2")}
      {R("M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2")}
      {L(10, 6, 14, 6)}
      {L(10, 10, 14, 10)}
      {L(10, 14, 14, 14)}
      {L(10, 18, 14, 18)}
    </Svg>
  ),
  "/contacts": (
    <Svg>
      {L(16, 2, 16, 4)}
      {L(8, 2, 8, 4)}
      {R("M7 22v-2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2")}
      {C(12, 11, 3)}
      <rect x="3" y="4" width="18" height="16" rx="2" />
    </Svg>
  ),
  "/audit-events": (
    <Svg>
      {L(15, 12, 10, 12)}
      {L(15, 8, 10, 8)}
      {R("M19 17V5a2 2 0 0 0-2-2H4")}
      {R("M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3")}
    </Svg>
  ),
  "/users": (
    <Svg>
      {R("M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2")}
      {C(9, 7, 4)}
      {R("M22 21v-2a4 4 0 0 0-3-3.87")}
      {R("M16 3.13a4 4 0 0 1 0 7.75")}
    </Svg>
  ),
  // Ajuda
  "/wiki": (
    <Svg>
      {R("M12 7v14")}
      {R("M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z")}
    </Svg>
  ),
};
