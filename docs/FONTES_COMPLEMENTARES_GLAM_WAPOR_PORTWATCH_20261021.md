# NIVON — rodada de descoberta: fontes gratuitas que fecham lacunas (21/10/2026)

## Regra USDA: aproveitar a credencial já provisionada

A credencial USDA FAS (API.Data.gov) informada pelo usuário já está sob teste em outro fluxo do NIVON, com uso via segredo do GitHub e sem exposição do valor. **Não** abrir novo cadastro para FAS antes de verificar o secret existente. USDA NASS Quick Stats e AMS MyMarketNews usam credenciais específicas por serviço; a mesma chave FAS não autentica automaticamente nesses dois serviços. Confirmar tipo de chave existente por nome de secret e teste de serviço, nunca imprimindo tokens.

## Novas fontes desta rodada

| Dataset NIVON | Fonte e acesso gratuito | Aplicação relevante | Evidência e bloqueio |
| --- | --- | --- | --- |
| NASA_USDA_GLAM_NDVI | NASA/USDA GIMMS GLAM, https://glam1.gsfc.nasa.gov/api/doc/gettbl | séries NDVI VIIRS 500m / OLCI 300m para monitorar stress vegetativo | **Cliente manual HTTP implementado** em src/nivon/nasa_glam_ndvi.py. Precisa resolver IDs ADM GLAM, máscara agrícola apropriada, CSV real, unidades, versões e licença específica |
| FAO_WAPOR3_EVAPOTRANSPIRACAO | https://www.fao.org/in-action/remote-sensing-for-water-productivity/wapor-data-access/en ; API v3 sem token | evapotranspiração real, biomassa e produtividade hídrica, global 300m (camada L1) | FAO GISMGR v2 documentada. Falta resolver identificadores de camada, recorte espacial/temporal, baixar uma amostra real; não pressupor 100m/20m em MT |
| IMF_PORTWATCH_PORT_ACTIVITY | https://portwatch.imf.org/ ; catálogo OGC https://portwatch.imf.org/api/search/definition/ | escalas e volumes de carga marítima **estimados** a partir de AIS, por porto/grupo de embarcação; gargalos internacionais | Serviço de ArcGIS citado em projetos de terceiros https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Trade_Data/FeatureServer/0?f=pjson **retorna JSON erro 400** hoje; NÃO usar para coleta até descobrir recurso atual e confirmar direitos |
| GEOGLAM_CONDICAO_LAVOURAS | https://www.cropmonitor.org/archive | avaliações mensais de condição de soja, milho e trigo por regiões produtoras, com séries históricas/boletins | relatório qualitativo, não previsão quantitativa de produtividade; link de download e schema por edição pendentes |
| COPERNICUS_C3S_SAZONAL_ENS | https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels | ensemble de chuva e temperatura mensal/sazonal, nível probabilístico semanas-meses | fonte COPERNICUS_CDS já cadastrada. Requer conta/token CDS grátis, viés e versão do modelo. Não duplicar ERA5-Land |
| ANTT_PISO_MINIMO_FRETE | https://www.gov.br/antt/pt-br/assuntos/cargas/politica-nacional-de-pisos-minimos-de-frete | referência **legal mínima** por distância/tipo/coeficiente, comparável com frete negociado e diesel | valor não é preço do mercado. Fórmula oficial segundo regras vigentes: distância × CCD + CC; preservar tabelas e efeitos vigentes. Não criar valor sem ler portaria específica |

## Outras bases já catalogadas a aprofundar em vez de duplicar

- MDIC Comex Stat/NCM (exportação por produto, porto/URF, país; histórico desde 1997).
- ANP diesel (histórico de preços S10/S500), ANTAQ movimentação e ONTL infraestrutura, licenças e limitações por fonte.
- USDA FAS/PSD/Export Sales com secret existente e testes privados; NASA POWER e CHIRPS (meteorologia de grade), IBGE/SIDRA e CONAB (produção), CFTC COT (posicionamento, não cotação CBOT).
- ANA/HidroWebService: documentação oficial https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html inclui HidroSat, séries de chuva, cota, vazão, telemetria e qualidade. Acesso é autenticado; aproveitar conexão USDA/ANA/INMET em fluxo separado, sem confundir códigos municipais da ANA com IBGE.
- NASA/USDA GLAM *não substitui* o produto mensal consensual GEOGLAM Crop Monitor. Um é índice de satélite; outro é avaliação conjuntural de safra.

## Governança e prioridades

1. Homologar GLAM gettbl CSV com ID de área válido e máscara de soja/milho em países relevantes, preservando o ID GLAM independente do IBGE e sem chamar vegetação de produtividade.
2. Descobrir acesso PortWatch atual, uma observação validada de porto com campos e licença. Nunca inferir linha-up programado a partir de escalas observadas e não equiparar tonelada AIS com ANTAQ realizada.
3. WaPOR L1 300m no Brasil por recorte mínimo: dados modelados e escala adequada, qualificar pixel vs fazenda.
4. Integrar previsão C3S sazonal após credencial CDS e calibração, sem confundir probabilidades com previsão determinística.
5. Fechar referência piso ANTT (incluindo histórico de tabela e vigência), separada dos preços de frete negociados.

Os seis datasets e rotas foram registrados com **runtime_enabled=false**, **scheduled_enabled=false**, **collection_authorized=false**, direitos em revisão, publicação OFF e sem alteração do banco. Um conector manual HTTP/CSV novo GLAM foi codificado com validações e testes sintéticos. A implantação, downloads reais, integração de banco, cache e backfill ainda não foram comprovados.

Nenhuma licença paga, contratação, credencial ou operação de escrita na infraestrutura foi criada por esta rodada.

### Fontes oficiais
https://glam1.gsfc.nasa.gov/api/doc/gettbl
https://glam1.gsfc.nasa.gov/api/doc/db/versions
https://www.fao.org/in-action/remote-sensing-for-water-productivity/wapor-data-access/en
https://portwatch.imf.org/
https://portwatch.imf.org/api/search/definition/
https://www.cropmonitor.org/archive
https://climate.copernicus.eu/climate-data-store
https://www.gov.br/antt/pt-br/assuntos/cargas/politica-nacional-de-pisos-minimos-de-frete
