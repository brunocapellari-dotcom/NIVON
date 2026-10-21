# NIVON — clientes HTTPS de APIs gratuitas (21/10/2026)

## Execução implementada

Foram escritos clientes HTTPS em Python 3.11 (sem novas dependências), para Open-Meteo Forecast, Open-Meteo Archive, Banco Central SGS série 11 (Selic diária), World Bank v2, IBGE Localidades e NASA POWER. São cinco provedores e seis contratos de dados.

O módulo src/nivon/apis_gratuitas_execucao.py usa HTTPS com domínio e caminho verificados, sem redirecionamento, timeout de 15 segundos, limite de bytes, MIME JSON, SHA-256 e carimbo UTC da coleta. Reaproveita os parsers científicos já criados. Não faz scraping, agendamento, backfill em massa, gravação ou publicação. Para Banco Mundial foi escrito src/nivon/banco_mundial_indicadores.py, que valida indicador, pais BR, período, unidade, nulos e paginação.

## Uso manual pontual

Todos os comandos exigem --executar. Sem ele, nenhum HTTP é feito. Apenas metadados da consulta aparecem no terminal, não preços nem séries completas.

    PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte selic --executar
    PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte clima --latitude -13 --longitude -56 --dias 7 --executar
    PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte historico_clima --latitude -13 --longitude -56 --inicio 2026-09-01 --fim 2026-09-07 --executar
    PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte banco_mundial --indicador SP.POP.TOTL --inicio-ano 2020 --fim-ano 2025 --executar
    PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte nasa_power --latitude -13 --longitude -56 --inicio 2026-09-01 --fim 2026-09-02 --executar
    PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte ibge --executar

## Semântica e limites

- Open-Meteo Forecast são valores PROJETADOS por modelo; Archive e NASA POWER são modelados/reanálise, NÃO medição de estação, talhão ou pluviômetro.
- Selic SGS 11 é uma taxa diária percentual, não meta Selic anual. O dado inclui data de referência em DD/MM/AAAA.
- Banco Mundial produz indicadores macro anuais, não cotações de mercado; lastupdated é atualização de conjunto, não publicação de observação individual.
- IBGE usa códigos de 7 dígitos dos municípios, sem inferência por proximidade. O endpoint não fornece vigência histórica por município.
- Ausência de data de publicação resulta em NULL, nunca data inventada.

## Direitos e estado

Gratuidade de consulta não substitui licença por operação. Open-Meteo exige uso não comercial e atribuição; NASA, BCB, IBGE e Banco Mundial também exigem revisar condições de origem, transformação, armazenamento e divulgação. O usuário autorizou desenvolvimento reversível sem custos, mas não a ativação irrestrita ou contratação.

Catálogo e rotas permanecem com enabled=false, collection_authorized=false, runtime_enabled=false e scheduled_enabled=false. Não existe coleta contínua, banco persistente ou deploy neste incremento. O smoke executa apenas quando expressamente invocado por operador.

Testes offline E2E simulam HTTP com bloqueios para host malicioso, HTTP em vez de HTTPS, redirects, MIME inválido, status de erro, payload grande, país e indicador divergentes, paginação parcial, carimbos sem fuso, nulos e dados fora do modelo. A homologação HTTP real e persistência com versões e backup/restore seguem pendentes.

## Próximos conectores

INPE Queimadas precisa de recurso CSV exato, direitos e esquema real. USDA FAS requer chave gratuita API.Data.Gov armazenada como secret privado, CFTC usa Socrata COT (não preço CBOT). MDIC, ANP, CONAB e ANTAQ já possuem módulos próprios; dar prioridade a completar histórico real ao invés de duplicá-los.

Referências oficiais: https://open-meteo.com/en/docs ; https://open-meteo.com/en/terms ; https://datahelpdesk.worldbank.org/knowledgebase/articles/889392 ; https://dadosabertos.bcb.gov.br/ ; https://servicodados.ibge.gov.br/api/docs/localidades ; https://power.larc.nasa.gov/docs/services/api/temporal/daily/
