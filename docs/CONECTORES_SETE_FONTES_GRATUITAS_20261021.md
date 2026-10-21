# NIVON — Conectores concretos da rodada de sete bases (21/10/2026)

## Implementados nesta PR

Foram acrescentados clientes HTTPS pontuais, normalizadores e testes para **seis** bases que estavam sem módulo, reutilizando Earth Search STAC já criado na PR #88. Todas permanecem com `enabled=false`, `runtime_enabled=false`, `scheduled_enabled=false`, e sem agendamento, banco, custos e dados publicados.

| Dataset | Módulo | Operação real disponível | Limitação |
| --- | --- | --- | --- |
| USDA_AMS_GTR_FRETE_MULTIMODAL | `nivon.planilhas_publicas_xlsx.consultar_planilha` | GET `https://www.ams.usda.gov/sites/default/files/media/GTRTable1.xlsx` | Lê OOXML, sem publicar indicador numérico enquanto unidades e abas não forem homologadas contra XLSX real |
| USDA_AMS_GTR_PRECO_BASIS_EXPORT | `nivon.planilhas_publicas_xlsx.consultar_planilha` | GET `https://www.ams.usda.gov/sites/default/files/media/GTRTable2A_B.xlsx` | Preços e basis dos EUA: NÃO equivalem a preço físico Brasil nem histórico oficial CME licenciado |
| WB_PINK_SHEET_COMMODITIES | `nivon.planilhas_publicas_xlsx.consultar_planilha` | GET `https://thedocs.worldbank.org/en/doc/18675f1d1639c7a34d463f59263ba0a2-0050012025/related/CMO-Historical-Data-Monthly.xlsx` | XLSX mensal histórico, colunas e unidades ainda sem mapeamento numérico homologado |
| NOAA_ENSO_INDICES_HISTORICOS | `nivon.noaa_mei_v2.consultar_mei_v2` | GET `https://psl.noaa.gov/data/correlation/meiv2.csv` | MEI v2 é série de **bimestres móveis** DJ, JF ... ND. Não confundir com ONI ou RONI, nem afirmar publicação por período |
| ESA_WORLDCOVER_2021_10M | `nivon.georaster_catalogos.consultar_esa_tile` | HEAD de UMA tile 3°×3° em `esa-worldcover.s3.eu-central-1.amazonaws.com` | Verifica existência e tamanho remoto, **não baixa GeoTIFF** nem extrai classe de uso do solo; mapa é de 2021 |
| JRC_GSW_AGUA_SUPERFICIAL | `nivon.georaster_catalogos.consultar_jrc_wmts` | GET WMTS Capabilities público JRC 2024 | Catálogo **cartográfico**; sem raster numérico, não permite calcular área queimada, nível/vazão ou navegabilidade |
| EARTH_SEARCH_STAC_CENAS | `nivon.earth_search_stac.consultar_cenas` | Já implementado e reaproveitado | Consulta somente metadados de cenas, sem baixar imagens |

## Segurança e contrato

- XLSX: parser OOXML em biblioteca padrão: limites ZIP, nomes de arquivos, macros, conexões externas, 10 mil linhas/aba, 80 colunas, fórmulas descartadas (inclusive caches), sem executar links e sem interpretar preços antes de homologação da tabela.
- NOAA: CSV validado com 12 colunas bimestrais, sentinelas `-999` removidas, carimbo de coleta UTC, revisão e data de publicação não inferidas.
- ESA: cálculo exato da tile com múltiplos de 3°, HTTPS GET **não** realizado; usa HEAD somente para inventário, sem assumir que o objeto existe antes do retorno.
- JRC: somente XML do WMTS público, com avisos sobre migração Landsat Collection 1/2 e falhas conhecidas de recorrência da V1.5.
- Sem ativação automática, sem downloads em massa, sem credenciais, sem gastos e sem publicar dados que não passaram por teste HTTP real.

## Diagnósticos manuais

```bash
PYTHONPATH=src python scripts/smoke_gtr_noaa_geodata.py --fonte gtr_frete --executar
PYTHONPATH=src python scripts/smoke_gtr_noaa_geodata.py --fonte gtr_precos --executar
PYTHONPATH=src python scripts/smoke_gtr_noaa_geodata.py --fonte pinksheet --executar
PYTHONPATH=src python scripts/smoke_gtr_noaa_geodata.py --fonte mei --executar
PYTHONPATH=src python scripts/smoke_gtr_noaa_geodata.py --fonte esa --latitude -13 --longitude -56 --executar
PYTHONPATH=src python scripts/smoke_gtr_noaa_geodata.py --fonte jrc --executar
```

Os testes automatizados usam uma estrutura OOXML ZIP construída em memória e mocks HTTP (sem serviços externos). A suite CI deve cobrir erros de arquivo malformado, tamanho, chaves, redirects, estruturas temporais e segurança. A rede deste ambiente não resolve os servidores externos: **nenhuma das respostas de produção foi obtida nesta PR**.

## Próximos gates

1. Executar smoke real (GET/HEAD) num runner com rede autorizada; registrar somente resposta, latência, Content-Type, quantidade de linhas e SHA, nunca segredos.
2. Ajustar mapa semântico GTR e Pink Sheet por aba, coluna, unidades, data e indicador contra XLSX reais; não publicar valor até essa etapa.
3. Adicionar leitura seletiva de GeoTIFF via Range/COG com limite de bytes, validação de tile e CRS e tratamento de NoData, após evidência de necessidade para ROI.
4. Persistir observações e snapshots com data_referencia, data_publicacao, data_coleta, competencia, fonte, checksum e versão; homologar restauração e deduplicação.
5. Somente depois permitir agendamentos controlados e alimentação dos motores de tendência.

Documentação oficial:
- USDA AMS GTR: https://www.ams.usda.gov/services/transportation-analysis/gtr-datasets
- NOAA MEI v2: https://psl.noaa.gov/data/timeseries/month/MEIV2/
- Pink Sheet: https://www.worldbank.org/en/research/commodity-markets
- WorldCover: https://esa-worldcover.org/en/data-access
- JRC: https://global-surface-water.appspot.com/download
