# NIVON — ANTT e ANTAQ: transporte ferroviario e hidroviario

**Verificacao:** 22/10/2026 (23/10 UTC). **Estado:** prova HTTP LIVE ANTT/SIADE 2025-2026 bem-sucedida, parse e SHA conferidos em runner efemero. ANTAQ somente indicadores documentais de 2025. **Nao existe persistencia definitiva em GCP/BigQuery nem coleta recorrente homologada.** Prova: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39895847815.

### Evidencia LIVE ANTT — extraido da fonte, ainda nao conciliado

| Recorte | TU | Linhas | Referencia |
|---|---:|---:|---|
| Brasil 2025 completo | 555.077.765 | 7.802 | jan-dez/2025 |
| Brasil jan-ago/2026 | 353.466.337 | 5.081 | jan-ago/2026 |
| Origem MT, 2025 | 26.459.272 | — | 2025 |
| Origem MT, jan-ago/2026 | 18.796.441 | — | jan-ago/2026 |
| Soja Brasil 2025 | 38.504.745 | — | 2025 |
| Soja Brasil jan-ago/2026 | 35.374.858 | — | jan-ago/2026 |
| Milho Brasil 2025 | 18.085.177 | — | 2025 |
| Milho Brasil jan-ago/2026 | 4.088.904 | — | jan-ago/2026 |
| Farelo soja Brasil 2025 | 9.203.973 | — | 2025 |
| Farelo soja Brasil jan-ago/2026 | 7.337.609 | — | jan-ago/2026 |

Versoes: 2025 SHA256 `265a40f1759fcb6af5a83d28b687d3621d8cf50054ae777f80e7cb0d9e863114`; 2026 SHA256 `d5063b8f5af64e358bb02fe9189079839b09e765e288e7ce49fdaf30e196f1f8`.

**Alerta de conciliacao:** ANTT/SIADE reextraido apresenta 555,08 Mi TU em 2025, em vez de 554,48 Mi TU citados em publicacao secundária anterior. Trata-se de 0,60 Mi TU de divergencia a investigar (revisao da fonte, data-base, conceito ou regra de totalizacao). Nunca substituir silenciosamente o dado primario pela estatistica de imprensa.

CSV real confirmado `cp1252` (nao UTF-8), competencia `01/2026` e números `33.420`=33420 TU, `28.774.620`=28774620 TKU. O dicionario formal usa `MM_AA`; o leitor aceita ambas as variantes com testes. A consolidação preserva unidades e filtra grupos via descricao publicada, sem equivaler volume por ferrovia à carga unica porta-a-porta.


## Indicadores 2025 com recortes distintos

| Fonte | Recorte | Medida | Quantidade |
|---|---|---|---|
| ANTT/CNT | Ferrovia Brasil 2025 | TU | 554,48 milhoes |
| ANTT (comparativo ANTAQ) | Ferrovia Brasil 2025 | TKU | 408,20 bilhoes |
| ANTAQ/SDP | Navegacao interior estrita | t | 91,3 milhoes |
| Ministerio de Portos | Transporte em vias interiores, escopo amplo | t | aproximadamente 145 milhoes |
| ANTAQ | Navegacao interior estrita | TKU | 42,703889135 bilhoes |
| ANTAQ | Navegacao interior + cabotagem e longo curso em vias interiores | TKU | aproximadamente 114,59 bilhoes |

**Nao somar recortes sobrepostos.** TU e TKU nao sao medidas intercambiaveis. O TKU da ANTAQ envolve uma estimativa de distancia percorrida. Movimentacao portuaria nao equivale automaticamente a volume transportado unico por rota.

Fontes: https://agenciainfra.com/blog/transporte-ferroviario-de-cargas-cresce-26-e-registra-recorde-em-2025/
https://www.gov.br/antaq/pt-br/central-de-conteudos/noticias/2026/transporte-aquaviario-registra-crescimento-de-9-81-e-alcanca-374-6-bilhoes-de-tku-em-2025
https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/Anuario2025.pdf
https://www.gov.br/antaq/pt-br/central-de-conteudos/estudos-e-pesquisas-da-antaq-1/estudo-em-destaque
https://www.gov.br/portos-e-aeroportos/pt-br/assuntos/noticias/2026/05/mpor-faz-balanco-do-primeiro-bienio-da-secretaria-nacional-de-hidrovias-e-navegacao

## ANTT SIADE / OD

Catalogo: https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409

CSV 2025 e 2026: recursos especificados em src/nivon/transporte_multimodal.py. Historico em planilha publica de 2006 a agosto/2026:
https://www.gov.br/antt/pt-br/assuntos/ferrovias/dados-de-producao-do-transporte-de-carga-origem-destino

Campos divulgados: Mes_Ano, Ferrovia, Mercadoria_ANTT, Estacao_Origem, UF_Origem, Estacao_Destino, UF_Destino, TU, TKU. Catalogo atualizado em 02/10/2026, o que nao indica competencia outubro. Conferir escala TKU e formatos reais. Download pontual e incremental sob opt-in foi executado com sucesso para 2025-2026; os arquivos nao foram enviados ao banco e nao sao agendados. Catalogo CKAN intermitente em uma das provas (resposta nao JSON): observar rate-limit/instabilidade sem tentar contornar bloqueios.

## ANTAQ / SDP

Anuario e estudo oficial permitem referencias de toneladas e TKU, mas nao constituem um canal automatico de dados brutos. Familias de historicos portuarios: Atracacao, Carga, Carga_Hidrovia, Carga_Rio. Em 22/10/2026, o antigo download `https://estatistica.antaq.gov.br/ea/sense/download.html` redireciona ao aviso de manutencao publicado pela ANTAQ em 23/06/2026 e atualizado em 23/07/2026. Fonte: https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/publicacoes-off/painel-estatistico-aquaviario-indisponivel . A retomada do SDP para declaracao portuaria em outubro nao prova reativacao de download publico. Nao contornar bloqueios, nem imputar volumes.

## Requisitos para ativacao operacional

1. PROVA LIVE 2025-2026 CONCLUIDA em 23/10 UTC; pendente reconciliar totais com divulgacoes consolidadas e ampliar backfill CKAN 2006-2024.
2. Obter dados ANTAQ/SDP verificaveis por hidrovia, modal e mercadoria (e OD quando documentado), com contratos dos campos e direito de uso auditados.
3. Persistir versoes brutas com hash, competencia, publicacao e coleta; carregar agregados bitemporais para comparacao entre rodovia, ferrovia e hidrovia.
4. Publicar somente apos validacao da amostra real, conciliacao dos totais e controle de duplicatas e revisoes.
