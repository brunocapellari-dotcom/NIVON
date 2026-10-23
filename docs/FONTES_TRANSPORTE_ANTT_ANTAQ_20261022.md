# NIVON — ANTT e ANTAQ: transporte ferroviario e hidroviario

**Verificacao publica:** 22/10/2026. **Estado:** ANTT com parser testado offline e URLs anuais verificadas no catalogo oficial. ANTAQ somente indicadores documentais de 2025. **Nao existe ingestao LIVE nem escrita no banco nesta entrega.**

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

Campos divulgados: Mes_Ano, Ferrovia, Mercadoria_ANTT, Estacao_Origem, UF_Origem, Estacao_Destino, UF_Destino, TU, TKU. Catalogo atualizado em 02/10/2026, o que nao indica competencia outubro. Conferir escala TKU e formatos reais. Download pontual somente sob opt-in. Nao afirmar como coletado antes de HTTP real.

## ANTAQ / SDP

Anuario e estudo oficial permitem referencias de toneladas e TKU, mas nao constituem um canal automatico de dados brutos. Familias de historicos portuarios: Atracacao, Carga, Carga_Hidrovia, Carga_Rio. Exportacao historica foi reportada por terceiros como instavel/indisponivel; verificar em ambiente autorizado. Nao contornar bloqueios, nao imputar series.

## Requisitos para ativacao operacional

1. Executar probe de CSV ANTT real e reconciliar TU/TKU por ano, ferrovia e mercadoria.
2. Obter dados ANTAQ/SDP verificaveis por hidrovia, modal e mercadoria (e OD quando documentado), com contratos dos campos e direito de uso auditados.
3. Persistir versoes brutas com hash, competencia, publicacao e coleta; carregar agregados bitemporais para comparacao entre rodovia, ferrovia e hidrovia.
4. Publicar somente apos validacao da amostra real, conciliacao dos totais e controle de duplicatas e revisoes.
