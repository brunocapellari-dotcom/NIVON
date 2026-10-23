# NIVON — Prova de carga real ANTT/SIADE no Google Cloud (23/10/2026)

## Evidência de produção

**Carga ANTT/SIADE 2026 efetivamente realizada**, primeira escrita verificada no Google Cloud do NIVON:

- Workflow: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983416188
- Tentativa 1: falhou antes de escrever, por schema inesperado na resposta HTTP da ANTT.
- Tentativa 2: **sucesso**. Arquivo oficial fonte obtido, arquivado, tabela criada no BigQuery, registros e TU reconciliados via consulta após carga.
- Projeto: nivon-data.
- Dataset: nivon_raw, região southamerica-east1.
- Bucket: nivon-data-raw-2026, região southamerica-east1.
- Tabela: nivon-data.nivon_raw.antt_ferrovia_od_snapshots.
- View de revisão atual: nivon-data.nivon_raw.vw_antt_ferrovia_od_atual.
- Competências declaradas: janeiro–agosto de 2026.
- 5.081 registros OD, 353.466.337 toneladas úteis.
- CSV bruto: 393.698 bytes.
- SHA-256: d5063b8f5af64e358bb02fe9189079839b09e765e288e7ce49fdaf30e196f1f8.
- GCS estado: ARQUIVADO; BigQuery estado: CARREGADO_PENDENTE_CONCILIACAO.
- A verificação independente do piloto reconcilia COUNT e SUM(TU) com o lote após o job, com teto de 50 MB de bytes faturáveis na consulta.
- A revisão canônica é identificada por hash, com histórico append-only; sem sobrescrever o objeto no GCS.

## Primeira view quantitativa dos polos

- Workflow: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984168784
- Status: **sucesso**.
- View: nivon-data.nivon_raw.vw_nivon_corredores_ferrovia_mensal.
- Fonte base: revisão mais recente do SIADE em vw_antt_ferrovia_od_atual.
- Jan–ago/2026, TU por estação de **origem ferroviária** com nome geográfico exato:
  - Rondonópolis/MT: 17.248.940 t (116 linhas agregadas).
  - Alto Araguaia/MT: 1.084.192 t (17 linhas agregadas).
  - Itiquira/MT: 463.309 t (11 linhas agregadas).
- Por mercadoria de origem:
  - Rondonópolis: Soja 9.172.825 t; Farelo de Soja 3.516.545 t; Grãos - Milho 1.749.983 t; Álcool 1.462.640 t; Contêiner Cheio de 40 Pés 1.114.189 t.
  - Alto Araguaia: Farelo de Soja 759.195 t; Soja 291.064 t; Grãos - Milho 33.933 t.
  - Itiquira: Soja 372.101 t; Grãos - Milho 91.208 t.
- A fonte preserva mercadoria ANTT literal. A taxonomia normalizada só é usada nos casos explicitamente conhecidos, evitando inventar conteúdo de contêineres ou composição de produto.
- A ausência de Dom Aquino nesse recorte de ferrovias federais **não equivale a zero**. A ferrovia estadual exige fonte própria.

## Limites e próximos gates

**É comprovado:** acesso GitHub OIDC, GCS, tabela BigQuery, persistência e conciliação de 2026 e primeira view analítica.

**Não está comprovado nesta etapa:** histórico 2006–2025 gravado em BigQuery, atualização recorrente em produção, volumes rodoviários MDF-e completos, conciliação com ANTAQ, transbordos físicos, fretes pagos ou comércio individual.

O workflow recorrente da ANTT para Google Cloud permanece **bloqueado pelas variáveis independentes de aprovação**, para não iniciar gastos automáticos não delimitados. A operação do piloto não alterou esses gates. Custos reais devem ser acompanhados pelo faturamento GCP; resultados não significam custo zero.

Próxima prioridade: aprovar limites de custo da operação recorrente e realizar backfill histórico particionado; depois cruzar ferroviário com rodoviário, ANTAQ e cadastros de terminais, sem dupla contagem.
