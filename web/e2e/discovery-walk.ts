/** A caminhada do octeto do fumo da adoção (descoberta, parte 2).
 *
 * O nome deste arquivo NÃO pode ter `.spec` nem `.test`: o Playwright coleta
 * `e2e/**` (`testDir: "./e2e"`, sem `testMatch` próprio) e passaria a tratá-lo
 * como arquivo de teste.
 *
 * Por que a caminhada existe: o banco e2e é persistente e acumula autorizações,
 * e a adoção recusa prefixo que outra organização já tem ativo (409). Uma faixa
 * de bits fica parada pelo tempo do seu bit mais baixo — os bits 24-31 viram a
 * cada ~4,7 h, então duas rodadas na mesma tarde derivam o mesmo /24 —, e as
 * faixas que viram rápido repetem a cada 256 ms. O relógio dá o octeto de
 * partida, e ele anda até o primeiro livre nos dois /16 do RFC 2544. A recusa do
 * serviço é por SOBREPOSIÇÃO: um bloco menor dentro de um /24 ocupado não
 * escapa, e é por isso que a ocupação é medida por igualdade de /24 e que um
 * octeto ocupado em QUALQUER das duas famílias está ocupado.
 *
 * A função não lança: devolve `passos`, e quem chama é quem tem a mensagem
 * (`expect(passos, ...).toBeLessThan(256)`). `passos = 256` diz que a faixa
 * acabou.
 */
export function primeiroOctetoLivre(
  inicio: number,
  ocupados: Set<string>,
): { octeto: number; passos: number } {
  let octeto = inicio;
  let passos = 0;
  while (
    passos < 256 &&
    (ocupados.has(`198.18.${octeto}.0/24`) || ocupados.has(`198.19.${octeto}.0/24`))
  ) {
    octeto = (octeto + 1) % 256;
    passos += 1;
  }
  return { octeto, passos };
}
