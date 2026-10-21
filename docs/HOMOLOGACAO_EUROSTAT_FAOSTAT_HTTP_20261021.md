# NIVON — homologação Eurostat e FAOSTAT — 21/10/2026

## Implementações integradas na branch de desenvolvimento

- PR #106 https://github.com/brunocapellari-dotcom/NIVON/pull/106
  - Fonte nova EUROSTAT, dataset `EUROSTAT_OLEAGINOSAS_AREA` via `tag00100`, JSON-stat, **área mil hectares** em países da UE por cultura e ano.
  - Fonte FAO já existente, cliente REST no dataset `FAO_FAOSTAT_LONG_RUN` com país/cultura/ano/elemento delimitados. Testes offline aprovados; requisição real falhou por timeout, portanto NÃO homologada.
- PR #108 https://github.com/brunocapellari-dotcom/NIVON/pull/108
  - Dataset novo `FAO_FAOSTAT_BULK_CATALOGO`, endpoint oficial https://bulks-faostat.fao.org/production/datasets_E.json
  - O manifest contém tamanho, quantidade de linhas, nome/código dos domínios, URLs ZIP e data de atualização da fonte. URLs internas NÃO são acessadas automaticamente.

## Evidência HTTP real

Run: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39691373339

| Acesso | Resultado exato | Escopo validado |
| --- | --- | --- |
| Eurostat tag00100 França 2024 | PASSOU | 3 observações, JSON-stat decodificado, valor, dimensões, unidade mil ha, flags e SHA |
| FAOSTAT QCL API legado `fenixservices.fao.org` | FALHOU, TimeoutError | Não há resultado utilizável; falha ambiental/serviço, NÃO é prova de descontinuação |
| FAOSTAT Bulk Manifest `bulks-faostat.fao.org` | PASSOU | 69 domínios, 7 prioritários (QCL, RFB, RFM, PP, BE, TCL, TCLI), hash e metadados |

Workflow diagnóstico isolado na PR temporária #107, fechada **sem merge**. A cor verde do GitHub Actions não é evidência suficiente, porque as etapas são independentes com `continue-on-error`; os resultados foram lidos nas saídas individuais de cada passo.

## Limitações fundamentais

O **manifest FAOSTAT não é o próprio histórico agrícola**. QCL mostra ~33MB comprimidos e ~4,2 milhões de linhas, sujeitos a revisões; nenhuma carga ZIP de QCL foi executada. Acesso público à lista de datasets não prova direito de redistribuir todo conteúdo automaticamente. Avaliar licenças por operação.

Eurostat divulga a versão corrente sem reconstituir retrospectivamente todas as versões passadas. `updated` de dataset não pode substituir `data_publicacao` por observação. Comparações e backtests exigem vintages.

## Próxima ação técnica executável

1. Implementar leitura ZIP incremental/streaming a partir do manifest FAOSTAT, por domínios e filtro de país/cultura, com teto rígido de bytes, contagem máxima, nenhuma extração indiscriminada, schema FAOSTAT real e hashes de snapshot.
2. Validar uma única carga real em área de staging gratuita e temporária, com retorno de número de linhas, duplicatas e unidades, sem logs de séries numéricas ou licenças.
3. Ligar FAOSTAT/Eurostat ao banco analítico do NIVON após identificar a configuração de Google Cloud existente; sem criar nem ativar cobrança automaticamente.
4. Ativar atualizações somente após deduplicação, backup/restauração, controle temporal de revisões e limites documentados.

Contadores esperados do Catálogo Mestre nesta etapa: 117 fontes e 173 datasets/rotas; ambos os novos datasets continuam com `runtime_enabled=false`, `scheduled_enabled=false`.
