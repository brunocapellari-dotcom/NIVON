# NIVON — Comparador de revisões de programação PDF

**Data:** 21/10/2026  
**Estado:** TESTADO COM FIXTURES SINTÉTICAS / FONTES REAIS NÃO HOMOLOGADAS / SEM PUBLICAÇÃO.

## Objetivo

Identificar **mudanças entre edições de line-ups programados** de Paranaguá e Itaqui, sem confundir programação declarada com presença do navio, carga realizada, partida, cancelamento ou demanda de frete. O modelo ocupa a camada de **referências portuárias** `PdfProgrammeEdition`; não altera `LineupVintage`, estados AIS nem o motor de port calls.

## Contrato de comparação

- **Mesmo escopo:** porto, fonte, série, competência e **data de referência**. É vedado comparar Nº Prog de dias de referência distintos como se fosse identificador persistente de visita: a estabilidade temporal do número não foi comprovada. A coleta da segunda edição deve ser estritamente posterior à primeira.
- **Disponibilidade temporal:** `compare_pdf_programme_asof` aceita dois cortes passados, lê apenas edições publicadas **e** coletadas até cada corte e exige `read_authorized=True`. Sem duas edições disponíveis, retorna `DATA_GATED`, deltas nulos, nunca zero.
- **Nº Prog presente:** compara referências apenas dentro desse escopo; `IMO` e nome do navio não servem de substitutos. Nº Prog acrescido indica **nova referência de programação, não novo navio**. Nº Prog ausente no documento seguinte indica **não listado naquele documento**, não partida, carregamento ou cancelamento.
- **Programa com uma linha:** compara ETA informado, precisão de data/hora, produto declarado, volume **programado**, descrição do navio e DUV **literalmente declarado**. Mudança de DUV no PDF não comprova identificação definitiva da escala.
- **Programa com várias mercadorias:** permite pareamento restrito por nome de produto **presente e único** nos dois documentos. Produtos repetidos, faltantes e múltiplos lotes não possuem identidade estável suficiente; retornam `ambiguous_product_lot_lines_unmatched`, evitando associação por ordem da linha ou soma de quantidades.
- **Mistura de produtos:** quando o conjunto de rótulos muda em programa com várias linhas, as etiquetas não correspondidas são registradas como `unmatched_product_labels_unconfirmed`. Não afirmar que um lote foi incluído, retirado ou executado.
- **Linhas sem Nº Prog:** `unidentified_rows_not_reconciled` contabiliza apenas linhas sem associação temporal confiável. Não tenta unir por navio, IMO ou posição no arquivo.
- **Documento revisado sem delta de linha:** distingue checksum diferente do documento de mudanças declaradas nos campos. Checksum sozinho não certifica publicação/autenticidade.
- **Sem indicadores físicos:** `confirmed_port_calls`, `realized_tonnage_t`, `confirmed_departures` e `confirmed_cancellations` são sempre nulos. `publication_allowed=false`.

## Implementação

`src/nivon/maritime/pdf_programme_revisions.py`:
`ProgrammeChange`, `ProgrammeRevision`, `compare_pdf_programme_editions`, `compare_pdf_programme_asof`.

Reutiliza o `PdfProgrammeLedger` da PR #79 e as edições de PDF válidas da PR #67, sem criar novo banco, scraping, job agendado, fornecedor ou permissão de publicação. Histórico e backups do SQLite são responsabilidade de `MaritimeStore`, sob direitos explícitos.

## Evidência dos testes

- `tests/test_maritime_pdf_programme_revisions.py`: **28 testes sintéticos** das classificações, escopo, diferenças temporais, ambiguidades, alterações de produtos/volumes/ETA, provas não físicas, controle de leitura e resultados reconstruídos do backup SQLite.
- `tests/test_maritime_pdfplumber_e2e.py`: **13 testes completos** com PDF binário **sintético válido** gerado por ReportLab e extraído por `pdfplumber`. Inclui duas edições consecutivas de Paranaguá alterando o ETA e de Itaqui sem Nº Prog; a primeira gera mudança de horário programado, a segunda permanece não reconciliada.
- [GitHub Actions — suíte Python no SHA b43d67193878f3bbfe8774f2d07f31d95c7c3d74](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671681966): **1.210 testes**; 18 ignorados na suíte leve (5 anteriores + 13 PDF testados separadamente), nenhuma falha; job isolado `validar-pdf-maritimo-offline` **13/13 aprovados**.
- [GitHub Actions — build do cockpit no SHA b43d67193878f3bbfe8774f2d07f31d95c7c3d74](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671682364): sucesso, **sem deploy**.

## Bloqueios e próximas etapas

1. Testar **no mínimo 3 edições oficiais reais e legalmente obtidas por fonte/série**, conferindo data de referência, timestamp de publicação com evidência, momento de coleta, hash dos bytes e layout das tabelas; textos indexados não bastam.
2. Validar com as autoridades se `Nº Prog` e eventuais códigos de operação possuem escopo e persistência temporal; **só** depois projetar mapeamento verificável `Nº Prog ↔ DUV` e comparações entre datas diferentes. Nenhum relacionamento por nome/IMO como atalho.
3. Desenvolver registro de auditoria de alterações de layout e linha, incluindo posição na página, produtos/lotes, campo DUV ausente e diferença de horários. Proteger a extração em caso de PDF ilegível, escaneado, grande ou não confiável.
4. Homologar direitos por operação (coleta, guarda, leitura interna, divulgação, redistribuição); revisar de forma independente e executar testes fora de amostra antes de permitir qualquer fluxo produtivo.
5. Manter PR empilhada e em **draft**, sem merge, deploy, AIS produtivo ou custos pagos.

**Estado final:** `CODE_TESTED_SYNTHETIC_ONLY / REAL_DATA_GATED / RIGHTS_NOT_HOMOLOGATED / RELEASE_BLOCKED`.
