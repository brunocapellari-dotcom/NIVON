# NIVON — Catálogo único de fontes

_Gerado automaticamente de `config/fontes.yaml`. Não edite este arquivo manualmente._

Data do catálogo: 2026-10-26.

Publicar significa redistribuir dado bruto no repositório público; exportar significa disponibilizar dados da fonte para fora do terminal privado. Negado até licença e modalidade de uso verificadas. A coluna tabela_destino é planejamento, não evidência de existência ou escrita.

Estados: `real`, `parcial`, `parado`, `so_conector`. Os estados foram auditados documentalmente, não por consulta direta ao BigQuery.

| ID | Nome e órgão | URL oficial | Licença / termo | Repositório | Exportar | Frequência | Frescor (h) | Classe | Destino planejado | Estado |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| ANTT_SIADE | ANTT — SIADE ferrovia (ANTT) | [fonte](https://www.gov.br/antt/pt-br/assuntos/ferrovias) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | OBSERVADO | `nivon_stage.antt_siade` | real |
| ANTT_RGI | ANTT — Anuário e RGI rodoviário (ANTT) | [fonte](https://www.gov.br/antt/pt-br/assuntos/dados-abertos) | a confirmar (termo a confirmar) | não | não | anual | 9600 | OBSERVADO | `nivon_stage.antt_rodoviario` | parcial |
| ANTAQ | ANTAQ — hidrovias e movimentação (ANTAQ) | [fonte](https://web3.antaq.gov.br/ea/sense/) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | OBSERVADO | `nivon_stage.antaq_movimentacao` | so_conector |
| CONAB_SAFRAS | CONAB — safras e balanços (CONAB) | [fonte](https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | ESTIMADO | `nivon_stage.conab_publicacoes` | parcial |
| CONAB_ARMAZENS | CONAB — armazéns cadastrados (CONAB) | [fonte](https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | OBSERVADO | `nivon_stage.conab_armazens` | so_conector |
| CEPEA | CEPEA/ESALQ — indicadores de preços (CEPEA/ESALQ/USP) | [fonte](https://www.cepea.org.br/br/indicador/soja.aspx) | CC BY-NC 4.0 ([termo](https://creativecommons.org/licenses/by-nc/4.0/legalcode.pt)) | não | não | dia_util | 72 | OBSERVADO | `nivon_stage.cepea_indicadores_privado` | parado |
| IMEA | IMEA — preços, fretes e cadeias (IMEA) | [fonte](https://www.imea.com.br/imea-site/) | a confirmar (termo a confirmar) | não | não | dia_util | 72 | OBSERVADO | `nivon_stage.imea_publicacoes_privado` | parado |
| BCB_PTAX | Banco Central — PTAX (Banco Central do Brasil) | [fonte](https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/) | ODbL 1.0 ([termo](https://opendatacommons.org/licenses/odbl/1-0/)) | não | não | dia_util | 48 | OBSERVADO | `nivon_core.ptax_quotes` | parado |
| BCB_SGS | Banco Central — SGS (Banco Central do Brasil) | [fonte](https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados) | ODbL 1.0 ([termo](https://opendatacommons.org/licenses/odbl/1-0/)) | não | não | dia_util | 72 | OBSERVADO | `nivon_stage.bcb_sgs` | so_conector |
| ANP_PPI | ANP — paridade de importação (ANP) | [fonte](https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos) | a confirmar (termo a confirmar) | não | não | semanal | 336 | ESTIMADO | `nivon_stage.anp_ppi` | so_conector |
| ANP_DIESEL | ANP — preços de diesel na revenda (ANP) | [fonte](https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis) | a confirmar (termo a confirmar) | não | não | semanal | 336 | OBSERVADO | `nivon_stage.anp_diesel` | so_conector |
| COMEXSTAT | MDIC — Comex Stat (MDIC) | [fonte](https://comexstat.mdic.gov.br/pt/home) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | OBSERVADO | `nivon_stage.comexstat` | so_conector |
| INMET | INMET — observações meteorológicas (INMET) | [fonte](https://portal.inmet.gov.br/dadoshistoricos) | a confirmar (termo a confirmar) | não | não | horaria | 6 | OBSERVADO | `nivon_stage.inmet_observacoes` | so_conector |
| ANA | ANA — hidrologia e séries (ANA) | [fonte](https://www.snirh.gov.br/hidroweb/) | a confirmar (termo a confirmar) | não | não | horaria | 12 | OBSERVADO | `nivon_stage.ana_hidrologia` | so_conector |
| OPENMETEO | Open-Meteo — previsão (Open-Meteo) | [fonte](https://open-meteo.com/en/docs) | CC BY 4.0 (dados); API gratuita apenas não comercial ([termo](https://open-meteo.com/en/terms)) | não | não | horaria | 12 | ESTIMADO | `nivon_stage.openmeteo_previsoes` | so_conector |
| ARG_MAGYP | Argentina — MAGyP/SAGyP (Secretaría de Agricultura da Argentina) | [fonte](https://www.magyp.gob.ar/) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | OBSERVADO | `nivon_stage.argentina_agro` | so_conector |
| ARG_BCRA | Argentina — BCRA indicadores (BCRA) | [fonte](https://www.bcra.gob.ar/) | a confirmar (termo a confirmar) | não | não | dia_util | 72 | OBSERVADO | `nivon_stage.argentina_bcra` | so_conector |
| MARITIMO_PORTWATCH | FMI — PortWatch tráfego marítimo (FMI/IMF) | [fonte](https://portwatch.imf.org/) | a confirmar (termo a confirmar) | não | não | diaria | 72 | ESTIMADO | `nivon_stage.maritimo_portwatch` | real |
| IBGE | IBGE — SIDRA/PAM/PPM (IBGE) | [fonte](https://apisidra.ibge.gov.br/) | a confirmar (termo a confirmar) | não | não | anual | 9600 | OBSERVADO | `nivon_stage.ibge_estatisticas` | so_conector |
| USDA | USDA — estatísticas e previsões (USDA) | [fonte](https://apps.fas.usda.gov/psdonline/app/index.html#/app/home) | a confirmar (termo a confirmar) | não | não | mensal | 1080 | ESTIMADO | `nivon_stage.usda_oferta_demanda` | so_conector |
| ZARC | MAPA — zoneamento de risco climático (MAPA) | [fonte](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/risco-agropecuario/zoneamento-agricola) | a confirmar (termo a confirmar) | não | não | anual | 9600 | ESTIMADO | `nivon_stage.zarc` | parcial |
| CEMADEN | CEMADEN — dados pluviométricos (CEMADEN) | [fonte](https://www.gov.br/cemaden/pt-br) | a confirmar (termo a confirmar) | não | não | horaria | 12 | OBSERVADO | `nivon_stage.cemaden` | so_conector |
| AGROBR_BIBLIOTECA | agrobr — biblioteca de conectores (Projeto agrobr) | [fonte](https://github.com/bruno-portfolio/agrobr) | MIT (somente software) ([termo](https://github.com/bruno-portfolio/agrobr/blob/main/LICENSE)) | não | não | por_versao | 8760 | CONFIRMADO_EXTERNAMENTE | `nivon_stage.agrobr_metadados` | so_conector |

## Observações de implantação

As tabelas são destinos propostos; `so_conector` não constitui prova de execução ou carga em GCP. O catálogo é inventário de fontes, não autorização de tráfego, scraping, reuso comercial ou redistribuição.

Para cada fonte, verifique a licença de seus dados de origem antes de habilitar exportação. A licença MIT do agrobr cobre a biblioteca, não o conteúdo coletado. O status jurídico `pendente` significa bloqueio externo.

## Ressalvas por fonte

- **ANTT_SIADE:** Carga ferroviária por ano e período; não extrapolar o lote real para todas as séries.
- **ANTT_RGI:** Subset rodoviário citado nos relatórios; cobertura e escrita final a reconciliar.
- **ANTAQ:** Não confundir registros agregados com eventos individuais de navios.
- **CONAB_SAFRAS:** Legado Neon; safra, competência, publicação e referência são conceitos distintos.
- **CONAB_ARMAZENS:** Cadastro e capacidade estática não são ocupação efetiva.
- **CEPEA:** CC BY-NC 4.0; acesso interno não comercial; não exportar nem incorporar dados no repositório.
- **IMEA:** Termos a confirmar; publicação não equivale necessariamente à data de referência.
- **BCB_PTAX:** Licença ODbL verificada na ficha oficial do conjunto PTAX; exportação bloqueada até garantir atribuição e obrigações aplicáveis.
- **BCB_SGS:** Licença ODbL verificada na ficha oficial da série SGS 11; o serviço pode impor limites de consulta diária.
- **ANP_PPI:** PPI publicado é indicador/metodologia, não cotação efetivamente negociada.
- **ANP_DIESEL:** Dados publicados por local e agregação; exigir unidade e período.
- **COMEXSTAT:** Agrobr pode normalizar acesso; licença da biblioteca não concede licença do dado.
- **INMET:** Diferenciar observações de previsão meteorológica.
- **ANA:** Frequência horária é de monitoramento; séries históricas e estações variam.
- **OPENMETEO:** Termos oficiais: API gratuita não comercial, com limites e atribuição; licenciamento dos dados não elimina limite do serviço.
- **ARG_MAGYP:** Produção estimada e comercialização observada devem ser identificadas por série.
- **ARG_BCRA:** Não substituir dados originais por agregadores sem proveniência.
- **MARITIMO_PORTWATCH:** Lote marítimo real; AIS e estimativa de capacidade não são line-up nem tonelagem realizada.
- **IBGE:** Estimativas estatísticas devem ser identificadas por indicador e edição.
- **USDA:** Preservar vintage de cada publicação.
- **ZARC:** Há legado Neon; não é receituário agronômico.
- **CEMADEN:** Pontos de estação e lacunas de série precisam ser auditados.
- **AGROBR_BIBLIOTECA:** MIT cobre o software, NÃO os dados da fonte subjacente; não habilitar exportação por herança. Software MIT pode ser usado no código; metadados de terceiros não são liberados.

Validação determinística: `python config/gerar_fontes.py --check`. Regeneração: `python config/gerar_fontes.py`.
