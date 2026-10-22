# NIVON — lote incremental de conectores gratuitos (21/10/2026)

## Resumo do que foi realmente implementado

**Branch de base:** PR #119, que já incorpora em estágio de revisão 118 fontes/176 datasets e código para SIDRA, NASA POWER, Open-Meteo, FAOSTAT, CONAB, MDIC e outros. Este lote não duplica parsers existentes.

- Fonte: src/nivon/fontes_abertas_lote.py — **12 famílias de consulta pública**: 6 CKAN de datasets, Copernicus STAC, UN Comtrade preview e 4 APIs com chave gratuita.
- Fonte: src/nivon/arquivos_publicos_lote.py — **15 classes de arquivo CSV/ZIP-CSV** já obtido legalmente pelo usuário/fonte, apenas inspeção de schema, hashes e contagem.
- Smoke: scripts/consulta_fontes_gratuitas.py. Execução sem --executar bloqueia a rede.
- Testes: tests/test_fontes_abertas_lote.py, tests/test_arquivos_publicos_lote.py.
- **Não houve** ingestão real no banco, agendamento, liberação de redistribuição, download de arquivos de dados, implantação em cloud, habilitação do runtime ou pagamento. Resultado de teste mock não é homologação real.

## APIs novas com uma consulta HTTPS controlada

| ID | Host/contrato | Escopo efetivamente disponível |
| --- | --- | --- |
| MAPA_ZARC | dados.agricultura.gov.br — CKAN package_show | Inventário de arquivos por safra (não baixa CSV) |
| MAPA_SISZARC | dados.agricultura.gov.br — CKAN package_show | Inventário de arquivos do SISZARC; pode falhar se pacote removido |
| MAPA_SIPEAGRO | dados.agricultura.gov.br — CKAN package_show | Inventário de cadastros; não pressupõe atualização |
| ANTT_CIOT | dados.antt.gov.br — CKAN package_show | Inventário CIOT; não interpreta operações como toneladas |
| ANTT_RNTRC | dados.antt.gov.br — CKAN package_show | Inventário RNTRC; sem dados individuais/PII |
| BCB_MDCR | dadosabertos.bcb.gov.br — CKAN package_show | Descoberta API OData/recursos do SICOR, **não** extração OData |
| UN_COMTRADE_PREVIEW | comtradeapi.un.org — /public/v1/preview/C/A/HS | Consulta limitadíssima de um ano/HS/país/fluxo, retorna contagem sem promover totais |
| COPERNICUS_STAC_CATALOG | stac.dataspace.copernicus.eu — /v1/collections | Metadados de uma coleção Sentinel-2 L2A, sem baixar cenas nem imagens |
| NOAA_CDO | www.ncei.noaa.gov — /cdo-web/api/v2/datasets | Descoberta de datasets com token gratuito |
| FRED | api.stlouisfed.org — /fred/series/observations | Amostra de até 100 registros de série whitelist, sem interpretação temporal |
| USDA_NASS | quickstats.nass.usda.gov — /api/api_GET/ | Consulta pontual de cultura/ano nacional, sem normalização dos valores |
| EIA | api.eia.gov — /v2/petroleum/pri/gnd/ | Metadados de petróleo/combustíveis, não preços homologados |

Nota: os identificadores acima são identificadores de **adapters de consulta**, não novos datasets canônicos numéricos. Não foram criados IDs redundantes no catálogo mestre. O inventário será reconciliado com os IDs canônicos existentes; não converter consulta de METADATA para status de séries REAL_SNAPSHOT_TESTED.

## Arquivos CSV/ZIP homologáveis apenas após contrato real

Classes técnicas aceitas pelo inspecionador: MAPA_ZARC, MAPA_SISZARC, MAPA_SIPEAGRO, MAPA_SEGURO_RURAL, ANTT_CIOT, ANTT_RNTRC, ANTT_DNIT_TRAFEGO, ANP_DIESEL_PRECO, ANP_MOVIMENTACAO, MDIC_COMEX_NCM, MDIC_COMEX_MUNICIPIO, ANTAQ_MOVIMENTACAO, USDA_ERS_CUSTOS, FAOSTAT_CSV e MAPA_SIPEAGRO_FERTILIZANTES.

São rótulos do **inspecionador**, não licença confirmada nem schema científico. Para arquivos ZIP, só se aceita 1 CSV plano, sem caminho ou symlink, no máximo 8 MB compactados, até 16 MB extraídos, razão <=50 e 100 mil linhas. CSV malformado é rejeitado. Arquivos gigantes Comex e GeoTIFF/NetCDF precisam de pipeline de streaming especializado, **não** passam pelo leitor de amostras.

## Fontes já com módulos/rotas na PR #119 e não duplicadas

IBGE SIDRA PAM, localidades IBGE, USDA FAS PSD autenticação isolada, CONAB armazéns/safra, ANA HidroWebService, INMET histórico e catálogo, CPTEC via BrasilAPI, NASA POWER, Open-Meteo, GloFAS, FAOSTAT bulk/QCL, USDA GTR XLSX, NOAA MEI, World Bank Pink Sheet, INPE focos, Earth Search STAC, JRC WMTS, ESA WorldCover, SoilGrids REST (pausado e não deve ser ligado), SISFOGO ROI parser offline, ANP diesel, ANTT ferrovias, MDIC Comex arquivos, CEPEA/IMEA CSV supervisionado.

A existência do código dessas fontes NÃO confirma coleta ativa ou persistência atual.

## Dependências externas / não incluídas como gratuitas irrestritas

- CEPEA API oficial, CME/CBOT e fontes de acesso comercial: não classificar como custo zero.
- IMEA: não existe autorização formal de API automatizada demonstrada; importação autorizada já está em outra PR.
- CONAB SISDEP: CAPTCHA; não contornar.
- Embrapa Agritec/ClimAPI/SATVeg: testes temporários, não gratuidade permanente. Outras AgroAPI com franquia exigem conta e validação.
- NOAA CDO: NIVON_NOAA_CDO_TOKEN; FRED: NIVON_FRED_API_KEY; USDA NASS: NIVON_USDA_NASS_API_KEY; EIA: NIVON_EIA_API_KEY; **não usar a chave FAS/PSD automaticamente para NASS**.
- Copernicus STAC público permite catálogo sem login, mas aquisição de assets requer avaliar licença, quota e autenticação.
- CHIRPS/CHIRPS-GEFS, MapBiomas, GAEZ, SoilGrids arquivos, ONTL/shapefiles, OpenStreetMap PBF, NASA FIRMS, Comex bases volumosas e ANTAQ em grande escala: entrada futura específica de dados geoespaciais ou streaming; nenhum conector numérico completo neste lote. NASA FIRMS requer chave gratuita.
- AISStream oferece plano gratuito declarado, mas acesso real, direitos de retenção e cobertura brasileira dependem de chave e validação técnica.
- ANP Revendedores: endpoint JSON específico com paginação ainda não foi verificado. Não incluir scraping ou endpoint inventado.

## Segurança e comandos

- Sem rede por padrão; para consulta de **um** catálogo:
  PYTHONPATH=src python scripts/consulta_fontes_gratuitas.py --fonte MAPA_ZARC --executar
- Para amostra UN Comtrade (sem chave):
  PYTHONPATH=src python scripts/consulta_fontes_gratuitas.py --fonte UN_COMTRADE_PREVIEW --ano 2025 --executar
- Para NCEI/FRED/NASS/EIA, chaves no ambiente privado; stdout resume status e hash, nunca URLs com tokens.
- CI: PYTHONPATH=src python -m unittest discover -s tests -v

### Gates pendentes, obrigatórios por dataset

Direito de consulta/coleta/armazenamento, teste live pontual, schema REAL, QC/metodologia, separação de OBSERVADO/ESTIMADO/PROJETADO, referência/publicação/coleta/competência, processamento incremental, idempotência, backup/restauração e autorização de publicação. Até esses gates: runtime_enabled=false e scheduled_enabled=false, sem custos.

Fontes documentais: https://dados.agricultura.gov.br/ ; https://dados.antt.gov.br/ ; https://dadosabertos.bcb.gov.br/dataset/matrizdadoscreditorural ; https://uncomtrade.org/docs/un-comtrade-api/ ; https://documentation.dataspace.copernicus.eu/APIs/STAC.html ; https://www.ncei.noaa.gov/cdo-web/webservices/v2 ; https://fred.stlouisfed.org/docs/api/fred/series_observations.html ; https://quickstats.nass.usda.gov/api ; https://www.eia.gov/opendata/


## Download pontual de amostras CKAN com licença declarada

Código adicional src/nivon/coleta_ckan_csv_pontual.py e teste
tests/test_coleta_ckan_csv_pontual.py disponibilizam **uma amostra CSV oficial
por execução** para MAPA_ZARC ou ANTT_CIOT. A execução é **OFF por padrão**,
exige o UUID do recurso obtido do catálogo e verifica a licença declarada no
CKAN (cc-by e variantes permitidas), host oficial, caminho
/dataset/.../resource/.../download/...csv, MIME CSV, tamanho de até 8 MB,
não-redirect e hash dos bytes. Faz até **dois GETs**: metadados e um CSV; não
pagina, não cria backfill e não salva dados.
A saída é um relatório de schema e quantidade de registros, jamais números
interpretados automaticamente. Licença declarada pelo catálogo é apenas gate
inicial: uso, qualidade e direitos de publicação continuam pendentes. URLs
que apontam a hosts de armazenamento externos não são seguidas e pedem
verificação independente.

Exemplo manual controlado (substitua pelo UUID oficial da edição desejada):

    PYTHONPATH=src python -c "from nivon.coleta_ckan_csv_pontual import coletar_amostra_csv; print(coletar_amostra_csv(fonte='MAPA_ZARC',recurso_id='139e5a60-1f43-4cc8-aeab-a35dbbf816c0', executar=True)['estado'])"

Esse comando **não foi executado com rede real neste lote**. Usar apenas uma
consulta pontual controlada após verificar termos e orçamento de rede.
