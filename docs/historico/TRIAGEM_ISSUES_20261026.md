# Triagem das issues da reorganização — 26/10/2026

**Estado consultado:** 31 issues abertas no inventário inicial; a #303 foi encerrada com justificativa e ficaram 30 abertas. Não se conclui execução técnica ao mover issue.

| Issue | Trabalho | Decisão | Labels aplicados |
|---|---|---|---|
| [#303](https://github.com/brunocapellari-dotcom/NIVON/issues/303) | Mandato autônomo antigo | **FECHAR — executado**; substituído por diretrizes de cinco frentes em 26/10/2026 | `frente:F1`, `tipo:reorg` |
| [#300](https://github.com/brunocapellari-dotcom/NIVON/issues/300) | [P1][Codex] Painel operacional e boletins: dados reais, fonte e estado de ausência | MOVER — frente:F3 | `frente:F3`, `tipo:reorg` |
| [#299](https://github.com/brunocapellari-dotcom/NIVON/issues/299) | [P1][Codex] Motores quantitativos: backtest point-in-time e bloqueio de séries não homologadas | MOVER — frente:F3 | `frente:F3`, `tipo:reorg` |
| [#298](https://github.com/brunocapellari-dotcom/NIVON/issues/298) | [P1][Codex] Observabilidade go-live: erros, custo e freshness sem expor segredos | MOVER — frente:F5 | `tipo:reorg`, `frente:F5` |
| [#297](https://github.com/brunocapellari-dotcom/NIVON/issues/297) | [P1][Codex] Coletores oficiais recorrentes: freshness, retentativas e idempotência | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#296](https://github.com/brunocapellari-dotcom/NIVON/issues/296) | [P0][Codex] Neon → BigQuery: reconciliação PIT e plano de cutover reversível | MOVER — frente:F2 | `tipo:reorg`, `frente:F2` |
| [#295](https://github.com/brunocapellari-dotcom/NIVON/issues/295) | [P1][Codex] ANP diesel: identificar fonte oficial, frescor e conector reaproveitável | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#294](https://github.com/brunocapellari-dotcom/NIVON/issues/294) | [P1][Codex] Backfill GCS → BigQuery reprodutível e recuperação sem duplicar dados | MOVER — frente:F2 | `frente:F2`, `tipo:bug` |
| [#293](https://github.com/brunocapellari-dotcom/NIVON/issues/293) | [P1][Codex] Motor de line-up: reconciliação CDP/AIS e status portuário verificável | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#292](https://github.com/brunocapellari-dotcom/NIVON/issues/292) | [P0][Codex] Auditorar cadeia CEPEA/IMEA/CONAB existente e fechar lacunas E2E | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#291](https://github.com/brunocapellari-dotcom/NIVON/issues/291) | [P0][Codex] Radar de freshness das fontes usadas no terminal (sem dados inventados) | MOVER — frente:F4 | `frente:F4`, `tipo:bug` |
| [#290](https://github.com/brunocapellari-dotcom/NIVON/issues/290) | [P0][Codex] Diagnóstico de operação, regressão e rollback do terminal GCP | MOVER — frente:F2 | `frente:F2`, `tipo:bug` |
| [#289](https://github.com/brunocapellari-dotcom/NIVON/issues/289) | [P0][Codex] Terminal ANTT/SIADE: prova de leitura, freshness e ausência de dados | MOVER — frente:F3 | `frente:F3`, `tipo:bug` |
| [#288](https://github.com/brunocapellari-dotcom/NIVON/issues/288) | [P0][Codex] Pré-voo Google Cloud read-only para go-live privado NIVON | MOVER — frente:F2 | `tipo:reorg`, `frente:F2` |
| [#287](https://github.com/brunocapellari-dotcom/NIVON/issues/287) | [P0][Codex] Unificar PR #276 e terminal da main: uma interface privada verificável | MOVER — frente:F3 | `frente:F3`, `tipo:reorg` |
| [#286](https://github.com/brunocapellari-dotcom/NIVON/issues/286) | [P0][Codex] Retirar Vercel do repositório e preservar terminal no Google Cloud | MOVER — frente:F2 | `tipo:reorg`, `frente:F2` |
| [#281](https://github.com/brunocapellari-dotcom/NIVON/issues/281) | [P0 GO-LIVE] Publicar NIVON com URL verificável, dados reais e acesso controlado | MANTER — macro-issue | `frente:F3`, `tipo:reorg`, `bloqueado:bruno` |
| [#280](https://github.com/brunocapellari-dotcom/NIVON/issues/280) | [P1][Codex Cloud] Argentina MAGyP — revisão incremental e replay sem duplicidade | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#279](https://github.com/brunocapellari-dotcom/NIVON/issues/279) | [P1][Codex Cloud] Meteorologia e hidrologia — E2E, frescor e validação temporal | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#278](https://github.com/brunocapellari-dotcom/NIVON/issues/278) | [P1][Codex Cloud] Marítimo — conciliar AIS, CDP e line-up com evidência e incerteza | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#277](https://github.com/brunocapellari-dotcom/NIVON/issues/277) | [P0][Codex Cloud] Terminal privado NIVON — prova E2E e prontidão de go-live | MOVER — frente:F3 | `frente:F3`, `tipo:reorg` |
| [#264](https://github.com/brunocapellari-dotcom/NIVON/issues/264) | Plano de correções remanescentes — NIVON auditoria externa Gemini/Grok/Claude | MANTER — macro-issue | `tipo:reorg`, `frente:F5` |
| [#263](https://github.com/brunocapellari-dotcom/NIVON/issues/263) | P0 Auditoria C1 — proteger main, separar WIF/IAM e auditar faturamento | MOVER — frente:F5 | `tipo:reorg`, `frente:F5`, `bloqueado:bruno` |
| [#145](https://github.com/brunocapellari-dotcom/NIVON/issues/145) | P1: restaurar frescor CEPEA após indisponibilidade da fonte primária | MOVER — frente:F4 | `frente:F4`, `tipo:bug` |
| [#144](https://github.com/brunocapellari-dotcom/NIVON/issues/144) | [P0] Restabelecer extração oficial ANTAQ para toneladas por hidrovia e produto | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#143](https://github.com/brunocapellari-dotcom/NIVON/issues/143) | [P0] Persistir ANTT SIADE no Google Cloud com cargas incrementais e versionamento | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#142](https://github.com/brunocapellari-dotcom/NIVON/issues/142) | ANTT MDF-e — obter arquivo/API oficial da matriz origem–destino rodoviária | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#131](https://github.com/brunocapellari-dotcom/NIVON/issues/131) | P0/P1 — Homologar direitos, vintages e Hermes antes de promover PAM para o NIVON | MOVER — frente:F5 | `tipo:reorg`, `frente:F5` |
| [#94](https://github.com/brunocapellari-dotcom/NIVON/issues/94) | P0 — Implantar CEPEA, IMEA e CONAB no núcleo de dados NIVON | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#59](https://github.com/brunocapellari-dotcom/NIVON/issues/59) | NIVON — Persistir PTAX e homologar dados físicos de soja/milho | MOVER — frente:F4 | `frente:F4`, `tipo:fonte` |
| [#25](https://github.com/brunocapellari-dotcom/NIVON/issues/25) | [P0][Quant] Frete: impedir tendência agregada por município sem estabelecimento/transportadora comparáveis | MOVER — frente:F3 | `frente:F3`, `tipo:bug` |

## Distribuição das abertas

- frente:F2: 5 issue(s)
- frente:F3: 7 issue(s)
- frente:F4: 14 issue(s)
- frente:F5: 4 issue(s)

## Significado
- **MANTER:** issue agregadora com gate de aceite ainda não comprovado.
- **MOVER:** associada à frente indicada; não fechar nem afirmar pronta até evidência e revisão de Claude.
- **FECHAR:** apenas #303, encerrada no GitHub com comentário explicativo.
- `bloqueado:bruno` significa decisão humana necessária para produção, IAM ou custos; não atribui autorização automática.

As labels `frente:F1` a `frente:F5`, `tipo:bug`, `tipo:reorg`, `tipo:fonte`, `bloqueado:bruno` foram criadas/aplicadas na classificação.

**Revisão de escopo:** o destino detalhado de questões transversais (por exemplo, segurança e observabilidade) pode ser ajustado por Claude, sem alterar código alheio.
