# NIVON — verificação HTTP de GloFAS, ensemble e preços FAO — 21/10/2026

## Implementação rastreável

A base canônica de fontes do NIVON recebeu **4 datasets novos** em provedores já existentes (OPEN_METEO e FAO), sem fontes duplicadas:

- `OPEN_METEO_GLOFAS_VAZAO` — previsão de vazão fluvial **modelada**, m³/s/dia, grade ~5 km, distinto de observação ANA e de condição operacional de navegação.
- `OPEN_METEO_ENSEMBLE_PRECIP_MEMBROS` — previsões de chuva GFS ensemble em mm, membros independentes e controle separados. Probabilidade e confiança exigem calibração histórica e não são observação.
- `FAO_FPMA_SERIES_CATALOGO` — consulta oficial de UUID de séries, mercados e unidades.
- `FAO_FPMA_PRECOS_SERIES` — série oficial por UUID/periodicidade, preços no contexto original. Deve obter moeda, medida, praça e fonte do catálogo antes de expor indicadores ou índices relativos.

PR de código: https://github.com/brunocapellari-dotcom/NIVON/pull/102
PR de reparo dirigida por amostra real: https://github.com/brunocapellari-dotcom/NIVON/pull/104

## Evidência HTTP REAL

**Run:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39678334276

| Endpoint/dataset | Teste HTTP e normalizador | Evidência |
| --- | --- | --- |
| Open-Meteo Flood GloFAS /v1/flood | PASSOU | 3 datas diárias com SHA256 e coleta UTC |
| Open-Meteo Ensemble /v1/ensemble | PASSOU | 30 membros GFS, separados de `precipitation` (controle), SHA256 |
| FAO FPMA FpmaSerie/ filtrado Brasil | PASSOU | 31 séries de metadados, UUID canônico, SHA256 |
| FAO FPMA FpmaSeriePrice/ para UUID validado do catálogo | PASSOU | 128 observações históricas, paginação completa no teste |

O status acima foi lido **nos logs das quatro chamadas reais** (`CONSULTA_REAL_PONTUAL_SEM_PERSISTENCIA` para três delas e `FAO_PRECO_PONTUAL` para a quarta), e não inferido apenas do ícone verde do GitHub Actions. Os dados são amostras de resposta transitórias usadas na memória do processo; NÃO houve armazenamento no banco, cron, secrets, pagamento nem publicação automática.

A primeira chamada real do ensemble revelou uma coluna adicional `precipitation` (membro de controle) além dos `precipitation_member01..30`; a PR #104 incorporou validação da série de controle em vez de contá-la como membro perturbado. Houve novo HTTP real e os quatro testes passaram. O workflow de smoke usava `continue-on-error` por fonte para diagnosticar falhas independentemente; a PR temporária #103 foi fechada sem merge, evitando integrar debug ou disparadores permanentes.

## Limitações e próximos gates

1. Não comparar vazão GloFAS de um pixel a navegabilidade sem relacionar trecho do rio, cotas ANA, seções, profundidades, restrições, referência e calibração.
2. Ensemble: armazenar data/hora e execução do modelo (*run*) por observação, comparar previsões contra INMET/ANA e calibrar percentis e probabilidade; não assumir qualidade probabilística a priori.
3. FAO: cruzar UUID com metadados reais de moeda, medida, tipo de preço, mercado e revisão. Uma série de Brasil não significa automaticamente mercado físico de Mato Grosso.
4. Direitos: confirmar termos por operação, atribuição e cadência. O projeto tem fim não comercial; não inferir direitos de redistribuição.
5. Persistência ponta a ponta: implementar snapshots, checksum, deduplicação, datas `data_referencia`, `data_publicacao`, `data_coleta` e `competencia`, controle de erros e backup/restauração no banco do NIVON.
6. Só ativar publicação, backfill e coletas recorrentes depois de infraestrutura sem cobrança não autorizada, limites e auditoria.

Status de catálogo: `CODE_PRESENT` para os quatro datasets. `last_verified_data` na rota permanece `null` pelo contrato do Catálogo Mestre — este documento oferece a evidência HTTP separada sem declarar testes de persistência não realizados.

### Documentação primária

- https://open-meteo.com/en/docs/flood-api
- https://open-meteo.com/en/docs/ensemble-api
- https://fpma-documentation.web.app/docs/api-docs/time-series/
- https://fpma-documentation.web.app/docs/api-docs/series-price/
