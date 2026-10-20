# NIVON — auditoria da frente Coletores e Engenharia de Dados
**Data de corte:** 20/10/2026. **Base auditada:** branch feat/fontes-historicas-motores-cientificos-20261019, PR #9 (não mesclada). Não reproduz resultados de aquisição em produção.

## Resumo quantitativo reproduzível
- Fontes do catálogo: **101**; datasets: **139**; rotas: **139**; 15 domínios.
- Prioridades: P0: 42; P1: 78; P2: 19.
- Estágios do catálogo: BLOCKED_RIGHTS: 22; CANDIDATE: 39; CODE_PRESENT: 12; DISCOVERY_ONLY: 64; REAL_SNAPSHOT_TESTED: 2.
- Tipos de localizador: DIRECT_OFFICIAL_API: 2; DIRECT_PUBLIC_FILE: 5; NOT_VERIFIED_PER_DATASET: 95; OFFICIAL_DASHBOARD: 1; OFFICIAL_INDEX: 20; PROVIDER_PORTAL: 15; PUBLISHED_API_DOC: 1.
- **95** datasets sem URL específica verificada no catálogo; página institucional/documentação não é prova de endpoint.
- Todos os 139 registros de rota seguem runtime_enabled=false e scheduled_enabled=false nesta branch.
- Os 2 datasets em REAL_SNAPSHOT_TESTED designam experimentos de snapshot real declarados pelo projeto, **não** operações contínuas ou direitos comprovados para redistribuição.
- O teste de correspondência de nomes de módulos existentes a arquivos da branch não indicou referências órfãs, mas **não** prova importabilidade, conexão nem testes live.

## Prioridade P0 — um registro por dataset, sem contar páginas como integração
| Área | Dataset | Maturidade declarada | Localizador | Direitos da fonte |
|---|---|---|---|---|
| BALANCO | CONAB_BALANCOS | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| BALANCO | USDA_PSD | CANDIDATE | OFFICIAL_INDEX | REVIEW |
| BALANCO | USDA_WASDE_RELEASE_VINTAGES | CANDIDATE | NOT_VERIFIED_PER_DATASET | REVIEW |
| COMEX | MDIC_COMEX_MUNICIPIO_SH4 | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| COMEX | MDIC_COMEX_NCM | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| ENERGIA | ANP_IMPORTACAO_DIESEL | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| ENERGIA | ANP_PPI_COMBUSTIVEIS | CODE_PRESENT | DIRECT_PUBLIC_FILE | REVIEW |
| ENERGIA | ANP_PRECO_PRODUTOR_DIESEL | DISCOVERY_ONLY | OFFICIAL_INDEX | REVIEW |
| ENERGIA | ANP_PRECO_REVENDA_DIESEL | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| FERTILIZANTES | MDIC_COMEX_FERT | CANDIDATE | OFFICIAL_INDEX | REVIEW |
| GEO | IBGE_CODIGOS_MUNICIPIOS | CANDIDATE | PUBLISHED_API_DOC | REVIEW |
| INDUSTRIA | ABIOVE_SOJA_ESMAGAMENTO | DISCOVERY_ONLY | PROVIDER_PORTAL | REVIEW |
| INDUSTRIA | MAPA_SIPEAGRO_RACAO | REAL_SNAPSHOT_TESTED | DIRECT_PUBLIC_FILE | ATTRIBUTION_REVIEW |
| INDUSTRIA | SINDIRACOES_RACOES | DISCOVERY_ONLY | PROVIDER_PORTAL | REVIEW |
| LOGISTICA | ANTT_MDFE_RODOVIARIO | DISCOVERY_ONLY | OFFICIAL_DASHBOARD | REVIEW |
| LOGISTICA | ANTT_SIADE_FERROVIA | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| LOGISTICA | ANTT_TERMINAIS_FERROVIARIOS | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| LOGISTICA | CONAB_ARMAZENS_CAPACIDADE | CANDIDATE | DIRECT_PUBLIC_FILE | REVIEW |
| MACRO | BCB_PTAX | CODE_PRESENT | DIRECT_OFFICIAL_API | REVIEW |
| PECUARIA | IBGE_ABATE_FRANGO_1094 | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| PECUARIA | IBGE_ABATE_SUINO_1093 | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| PORTOS | ANTAQ_MOVIMENTACAO | CANDIDATE | PROVIDER_PORTAL | REVIEW |
| PORTOS | LINEUP_ARATU | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_BELEM | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_ITACOATIARA | BLOCKED_RIGHTS | NOT_VERIFIED_PER_DATASET | RESTRICTED |
| PORTOS | LINEUP_ITAGUAI | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_MANAUS | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_MIRITITUBA | BLOCKED_RIGHTS | NOT_VERIFIED_PER_DATASET | RESTRICTED |
| PORTOS | LINEUP_PARANAGUA | DISCOVERY_ONLY | PROVIDER_PORTAL | REVIEW |
| PORTOS | LINEUP_PORTO_VELHO | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_SANTANA | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_SANTOS | DISCOVERY_ONLY | PROVIDER_PORTAL | REVIEW |
| PORTOS | LINEUP_SAO_FRANCISCO_DO_SUL | DISCOVERY_ONLY | DIRECT_PUBLIC_FILE | REVIEW |
| PORTOS | LINEUP_SUAPE | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PORTOS | LINEUP_VITORIA | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| PRECOS | CEPEA_FISICO | BLOCKED_RIGHTS | NOT_VERIFIED_PER_DATASET | RESTRICTED |
| PRECOS | IMEA_FISICO | BLOCKED_RIGHTS | NOT_VERIFIED_PER_DATASET | RESTRICTED |
| RADAR | MAPA_SANIDADE_PROTEINAS | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | ATTRIBUTION_REVIEW |
| SAFRA | CONAB_GERGELIM_SERIES | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |
| SAFRA | CONAB_GRAOS_LEVANTAMENTOS | DISCOVERY_ONLY | NOT_VERIFIED_PER_DATASET | REVIEW |
| SAFRA | CONAB_GRAOS_SERIES | REAL_SNAPSHOT_TESTED | OFFICIAL_INDEX | REVIEW |
| SAFRA | CONAB_PROGRESSO_SEMANAL | CODE_PRESENT | OFFICIAL_INDEX | REVIEW |

## Desconexões concretas
1. **CONAB Semanal:** normalizador agrobr e SQLite histórico presentes; descoberta histórica do índice adicionada no PR #16 (offline). Downloads, direito de armazenamento/publicação, prova de edição e backfill completos ainda não comprovados.
2. **CONAB Armazéns:** arquivo TXT direto e parser existem; falta rodada ponta a ponta com arquivo oficial atual, cobertura geográfica, validação de CPFs/dados pessoais e histórico de capturas.
3. **MDIC/Comex:** plano anual de 1997 em diante, parsers CSV e reconciliação disponíveis; arquivos reais, mudanças de schema, versões históricas e persistência durável seguem não homologados. Dados da página MDIC não devem ser confundidos com dados de operação portuária.
4. **ANP diesel, ANTT ferrovia, BCB PTAX, IBGE PAM:** módulos offline e testes existem, mas aquisição operacional e publicação não estão liberadas. Para valores financeiros separar preço pesquisado, cotação oficial, estimativa e contrato negociado.
5. **ANA/INMET/clima:** existe processamento de dados ambientais e controle científico na branch #9; não presumir cobertura total de estações, horários ou que reanálise/estimativa satelital seja observação instrumental.
6. **Portos/line-up:** 45 datasets LINEUP_* representados no catálogo. A branch da PR #8 possui **19** módulos src/nivon adicionais ausentes na branch #9 analisada, incluindo antaq_historico_offline.py, antaq_zip_autorizado.py, diagnostico_portos.py, ingestao_lineup_portais.py, lineup_cdp_santarem.py, lineup_portais.py, qualidade_lineup.py. Conciliação deve ser coordenada pela frente de integração PR #13; não copiar sem comparação de contratos.
7. **Preços CME/ICE/CEPEA/IMEA:** sem fonte licenciada para coleta/republicação; permanecer BLOQUEADO. Não substituir silenciosamente cotações recentes por séries antigas.
8. **Fretes:** somente ofertas anunciadas com transportadora, ponto de embarque, destino, produto, condição, data, preço e procedência. Não usar média municipal nem inferir negócios realizados.
9. **Mapa, indústria, pecuária, balanços:** cadastros e alguns parsers estão presentes; lacunas de direitos, dados reais, temporalidade e identidade impedem classificá-los como cobertura operacional.

## Gates da frente para CI e integração
- Catálogo de fontes e rotas preservado como única fonte de verdade; não criar catálogo paralelo.
- Cada execução real futura deve ter prova de direitos por operação, URL/arquivo efetivo, hash SHA-256, timestamps de competência/referência/publicação/coleta, parser e schema, contagem de linhas, unidade, granularidade, classe de evidência, qualidade e resultado.
- O vazio tem valor NULL com razão explícita. Nunca inventar 0, preenchimento de semana, população de portos ou disponibilidade histórica.
- Incremental/backfill: versão da edição e época de conhecimento (*as-of*); reconciliação de duplicatas/republicações e resolução de port calls por escala quando disponível.
- Falhas: limites e retentativas com backoff e sem contornar proteção da fonte; quarantine, alerta e reaproveitamento somente de snapshot com validade comprovada.
- Operação: RAW privado imutável, banco com transações, backup remoto criptografado + restore demonstrado, segregação de credenciais, checagem de custo e auditoria de licenças.
- Pré-go-live: testes sintéticos + testes com dados reais autorizados + CI no SHA final + homologação independente e sem merge automático.

## Fontes oficiais conferidas nesta rodada (não equivalem a licença operacional)
- CONAB progresso semanal: https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra
- MDIC base bruta: https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta
- ANP série histórica: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis
- ANP dados de movimentação: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/dados-abertos-movimentacao-de-derivados-de-petroleo

## Estado de testes deste PR
Após alterações, consultar a execução GitHub Actions no HEAD da PR #16 e registrar SHA, data, número de testes e skipped. Não qualificar como homologação de HTTP real ou banco em produção.
