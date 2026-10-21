# NIVON — homologação pontual de sete conectores públicos (21/10/2026)

## Evidência de teste real

A implementação dos conectores foi mesclada à branch `integration/nivon-acessos-core-convergencia-20261021` nas PRs:

- PR #88 — Earth Search STAC: https://github.com/brunocapellari-dotcom/NIVON/pull/88
- PR #97 — seis conectores (NOAA, USDA GTR x2, WB Pink Sheet, ESA, JRC): https://github.com/brunocapellari-dotcom/NIVON/pull/97
- PR #99 — correções dirigidas por teste real: https://github.com/brunocapellari-dotcom/NIVON/pull/99
- PR #100 — sentinelas ausentes no CSV NOAA: https://github.com/brunocapellari-dotcom/NIVON/pull/100

Testes públicos pontuais executados em **GitHub Actions**:
https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39674715072

| Fonte | HTTP e parser na última execução | Escopo/resultado | Limites operacionais |
| --- | --- | --- | --- |
| NOAA MEI v2 | **PASSOU** | 572 registros com índice em bimestres móveis, sentinelas descartadas | Data de publicação exata não inferida; índices não são previsões |
| USDA AMS GTR Table 1 | **PASSOU** | 1.331 linhas estruturais XLSX | Indicador, unidade, vigência e metodologia por coluna **não homologados** |
| USDA AMS GTR Table 2A/2B | **PASSOU** | 7.002 linhas estruturais XLSX | Preço físico/spread EUA, sem converter para cotação de CBOT ou Brasil; mapeamento pendente |
| World Bank Pink Sheet XLSX | **PASSOU** | 2.655 linhas estruturais XLSX | Valores brutos, nomes/unidades por coluna ainda não homologados |
| ESA WorldCover 2021 | **PASSOU** | HEAD do arquivo oficial de uma tile, HTTP 200 e tamanho remoto validado | **Não baixou GeoTIFF nem pixel**, snapshot **2021**, não 2026 |
| JRC Global Surface Water | **PASSOU** | XML WMTS Capabilities com 6 camadas | Metadado **cartográfico**, não dado quantitativo de área/vazão/navegabilidade |

**Earth Search STAC** foi implementado e testado offline na PR #88, mas **não fez parte** da bateria de seis testes HTTP reais descrita acima. Não classificá-lo como homologado remotamente a partir desse relatório.

Todos os resultados foram obtidos por chamadas pontuais explícitas em runner público, sem chaves, pagamento, persistência ou ativação de cron. O job usou `continue-on-error` para investigar fontes de forma independente: **o êxito confirmado vem das seis saídas `CONSULTA_PONTUAL_SEM_PERSISTENCIA` e do resumo por fonte nos logs**, não apenas da conclusão verde do workflow. A PR temporária de debug #98 foi fechada sem merge, preservando o histórico de testes e evitando workflow temporário de produção.

## O que ainda falta para dizer “dados conectados ao banco”

1. Resolver schema real e unidades/commodity/rota/data dos arquivos USDA AMS GTR e WB Pink Sheet, incluindo linhas de cabeçalho e notas metodológicas. Enquanto isso `valores_monetarios_publicaveis=false`.
2. Fazer persistência real e reprocessamento idempotente de snapshots com `competencia`, `referencia`, `publicacao`, `coleta`, versão, URL, SHA e data de coleta em banco do NIVON e backup/restauração auditados.
3. Para ESA e JRC, baixar somente pequenos recortes geográficos autorizados de GeoTIFF/COG e interpretar classes ou pixel quantitativo com NoData, CRS e resolução. WMTS RGB **não** substitui raster original.
4. Testar Earth Search STAC em consulta HTTP real e validar ao menos uma cena real em área limitada sem seguir href de terceiros.
5. Realizar validação de direitos por operação e liberar agendamento **por dataset**, com quotas, backoff, recuperação e monitoramento, após confirmar custo zero/mínimo.
6. Expor as séries aprovadas aos motores do NIVON apenas após auditoria metodológica e temporal.

## Estado canônico

- Fontes/datasets/rotas: **116/167/167** na branch de integração.
- Código presente para **32** datasets; status `CODE_PRESENT` significa apenas disponibilidade de código, **não ingestão em produção**.
- 2 datasets com status anterior `REAL_SNAPSHOT_TESTED`; este relatório não promove nenhum dataset para esse estado sem snapshots históricos persistidos.
- Nenhuma coleta automática, cron ou infraestrutura adicional ativados.

Os testes automatizados e HTTP dão evidência verificável de que os conectores de consulta funcionam em chamadas pontuais. **Não existe prova de carga atualizada no banco central do NIVON para estes sete datasets.**
