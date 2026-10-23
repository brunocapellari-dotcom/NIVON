# NIVON — ANTT/SIADE ferroviário no Google Cloud: 21 anos e corredores MT

**Data da auditoria:** 23/10/2026. **Estado:** fonte ferroviária carregada, versionada e conciliada para 2006–agosto/2026. Isso **não** significa que todo o NIVON ou os fluxos rodoviários/hidroviários estão em produção.

## Evidências independentes, executadas no Google Cloud real

- 2006–2021: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39999355921 (tentativa 2, 5 lotes, sucesso)
- 2022–2025: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39998589364 (4 anos, sucesso)
- 2026: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983416188 (tentativa 2, sucesso)
- Auditoria integral independente da view: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001461762 (**sucesso**)
- Corredores/mercadorias/destinos reais por estação: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001966549 (**sucesso**)

### Cobertura auditada

- **21 anos:** de janeiro/2006 a agosto/2026.
- **174.850 registros origem-destino ferroviários** na visão canônica, sem revisões sobrepostas.
- **9.952.668.869 toneladas úteis**, soma histórica **de 21 anos**, não volume anual ou carga física modal única.
- **2026 é parcial**, com competências até agosto.
- A auditoria executou uma consulta real à view no BigQuery: **18.708.950 bytes processados**; esse número não equivale diretamente à cobrança na fatura.
- Cada ano do histórico foi previamente reconciliado por contagem e TU após a escrita GCS+BigQuery, com identificação SHA-256; a auditoria final comparou o total da view com os 21 baselines anuais.
- Os CSVs brutos oficiais estão no bucket com nome de objeto baseado em hash; tabela historizada por ano/versão.

**Identidades e dados canônicos:**

- Projeto: nivon-data
- Dataset: nivon_raw
- Bucket: nivon-data-raw-2026
- Região: southamerica-east1
- Tabela: nivon-data.nivon_raw.antt_ferrovia_od_snapshots
- View canônica da revisão atual: nivon-data.nivon_raw.vw_antt_ferrovia_od_atual
- View mensal de corredores: nivon-data.nivon_raw.vw_nivon_corredores_ferrovia_mensal

## Polos de origem ferroviária em MT — 2024 versus 2025

| Polo (estação de origem) | 2024, TU | 2025, TU | Variação anual observada |
|---|---:|---:|---:|
| Rondonópolis | 24.689.320 | 24.258.027 | -1,75% |
| Itiquira | 530.454 | 742.649 | +40,00% |
| Alto Araguaia | 1.428.131 | 1.458.596 | +2,13% |
| Dom Aquino | sem observação no recorte | sem observação no recorte | não classificável |

**Critério de referência para classificação:** acima de +2% = alta de volume; abaixo de -2% = baixa; intervalo inclusivo ±2% = estabilidade. É comparação anual de TU ferroviária, **não previsão nem tendência de preço do frete**. A classificação de Dom Aquino é ausência de evidência ferroviária com correspondência exata de nome, **não zero de fluxo de caminhões**.

### Produtos embarcados e destinos ferroviários identificados em 2025

- Rondonópolis: soja **9.651.555 t**, milho **6.657.943 t**, farelo de soja **4.439.574 t**, além de álcool **1.707.759 t** e contêiner cheio de 40 pés **1.547.578 t** (conteúdo do contêiner desconhecido).
- Itiquira: soja **682.533 t** e milho **60.116 t**.
- Alto Araguaia: farelo de soja **964.861 t**, soja **273.390 t** e milho **220.345 t**.
- Rondonópolis → estação ferroviária Santos/SP: **14.691.491 t**; → Conceiçãozinha/SP: **5.813.646 t**; → Replan/SP: **1.844.868 t**.
- Itiquira → Conceiçãozinha/SP: **707.268 t**.
- Alto Araguaia → Santos/SP: **1.034.609 t**.

**Interpretação:** estações ferroviárias de origem/destino, não prova de descarga em um terminal rodoviário, de embarque portuário realizado por navio, de exportador/comprador ou de operação contratada. O conteúdo real de contêineres não é conhecido pelo código de mercadoria agregado.

## Governança, segurança e pendências

- Os carregamentos retrospectivos de 2006–2025 **foram concluídos**; não são mais uma lacuna de ingestão histórica.
- A carga foi controlada: lotes de até quatro anos, tetos de bytes/linhas, GCS append-only, BigQuery versionado por hash, execução não recorrente e conciliação de COUNT/SUM(TU).
- O coletor mantém contingência de CKAN por URL + SHA oficialmente observado em artefatos prévios, sem burlar bloqueios e bloqueando alterações de arquivo não comprovadas. Ver docs/ANTT_CKAN_CONTINGENCIA_COM_SHA_20261023.md.
- **Ainda não ativado:** atualização incremental periódica gravando em GCP. O workflow recorrente continua dependente de aprovações independentes; a nomenclatura antiga ZERO_COST não garante gratuidade.
- **Ainda não verificado:** orçamento, alerta de faturamento e custo efetivamente cobrado no Google Cloud. É necessária checagem da conta de faturamento, e alertas não impõem automaticamente teto.
- **Ainda separado:** volumes rodoviários ANTT MDF-e, hidrovias ANTAQ, reconciliação de transbordos, identificação de terminais e line-ups portuários.
- **Próxima execução recomendada:** monitorar atualização de 2026 no SIADE, revalidar documentação/licenciamento, integrar ANTAQ e fontes reais rodoviárias, e usar séries por polo/mercadoria na inteligência de corredores sem dupla contagem modal.
