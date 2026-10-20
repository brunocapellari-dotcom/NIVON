# NIVON — Auditoria e plano executivo da Inteligencia Pecuaria

Data de corte: 2026-10-20. Base: feat/fontes-historicas-motores-cientificos-20261019 (PR #9 empilhada sobre PRs #3/#1). Branch: feat/pecuaria-inteligencia-20261020.

## Evidencia e maturidade

- Bovinos: frentes existentes BOI e BEZERRO registram rendimento de carcaca, relacao de troca e identidade contábil de rebanho; nenhum ciclo completo ou preco previsto homologado.
- Aves e suinos: normalizador offline para SIDRA 1094 / 1093 em cadeias_adicionais.py; peso medio de carcaca, simulacoes de custo/margem, alertas qualitativos, backtest CAGR genérico. Nenhuma serie oficial de abate foi persistida e versionada para estas frentes por esta branch.
- Todas as tres cadeias: direitos, esquema historico da fonte e validacao de dados reais nao concluidos; nenhum scheduler, distribuicao comercial ou sinal probabilistico autorizado.
- A infraestrutura catalogada nao constitui captura de dados efetiva. Revisoes anteriores a uma primeira coleta nao podem ser reconstruidas como vintages de publicacao sem edicoes historicas autenticas.

## Entregas desta branch

- pecuaria_ciclos.py: simulador bovino por arroba de CARCACA, custo de reposicao e ciclo de engorda; simulador frango por ave alojada; simulador suino em terminacao; ração por formulacao explicitamente identificada.
- pecuaria_mercados.py: series separadas para BOI_GORDO (BRL_ARROBA_CARCACA), BEZERRO (BRL_CABECA), FRANGO_VIVO e SUINO_VIVO (BRL_KG_VIVO); timestamp com fuso, fonte, praça, hash, publicacao e coleta; resolucao de revisoes por ultimo vintage disponivel no corte.
- Tendencia OBSERVADA: mediana de tres variacoes homomes interanuais exigindo 15 meses contiguos. Nao confundir com PREVISAO.
- Baselines para futuro: walk-forward mensal comparando naive sazonal anual contra persistencia mensal; exigir >=12 folds, availability em cada cutoff e erro mensurado. Continuam nao homologados: nenhum intervalo de confianca, probabilidade, ensemble ou receita projetada.
- Nenhum modulo reimplementa coleta ou altera o contrato editorial do briefing.

## Plano de dados — fontes canonicas, sem nova fonte da verdade duplicada

Catalogos de operacao a preservar: config/fontes_nivon_master.v1.json, config/rotas_coleta.v1.json e config/matriz_produtos_indicadores.v1.json. Identificadores abaixo devem ser reutilizados e corrigidos, NAO duplicados.

| Prioridade | Fonte/dataset | Uso por cadeia | Trabalho objetivo | Gate |
| --- | --- | --- | --- | --- |
| P0 | IBGE SIDRA 1092 / IBGE_ABATE | bovino: cabecas, carcaças, sexo e tipo por recorte disponivel | confirmar API variaveis/periodos e amostras reais; normalizar por BR/UF, civil/trimestre | publicar/armazenar permitido por operacao |
| P0 | IBGE SIDRA 1093 / IBGE_ABATE_SUINO_1093 | suinos: abate inspecionado e carcaça | confrontar API, variaveis, unidades e revisoes | parser OFFLINE nao significa conector |
| P0 | IBGE SIDRA 1094 / IBGE_ABATE_FRANGO_1094 | frango: abate inspecionado e carcaça | mesmo processo, unidades KG/T explícitas | nao extrapolar a plantel |
| P0 | IBGE PPM / IBGE_PPM | rebanho bovino/suino e galinaceos | registrar estoque em referencia anual, especie/categoria/UF/municipio quando suporte | PPM nao e fluxo de abate; galinaceos nao sao so frangos de corte |
| P0 | MAPA PGA-SIGSIF / catalogo existente | tres especies: abates SIF e categorias | mapear relatorios CSV, modalidade publica, diferenciar cobertura MAPA do IBGE | nao somar SIF e IBGE |
| P0 | MDIC Comex Stat / MDIC_COMEX_NCM | carne bovina, aves, suina e cortes | NCM versionada por ano, sentido, destino, volume, FOB, revisoes | peso liquido de produto != equivalente carcaca |
| P1 | CEPEA_BOI / CEPEA_FISICO, SCOT_PECUARIA | boi, bezerro, aves e suinos quando licenciados | obter direitos e metadados de series, praca, regime e periodicidade | uso comercial/redistribuicao bloqueado ate aprovacao |
| P1 | EMBRAPA CIAS, ABPA_FRANGO_SETOR, ABPA_SUINO_SETOR | dietas, conversao, custos e balancos setoriais | integrar metodologias, datas e autorizacoes de cada publicacao | sem tratar indicadores como registro individual |
| P1 | USDA PSD / FAO FAOSTAT | comparacao de oferta, demanda e comercio internacional | normalizar unidades, ano comercial e series por revisao | coerencia temporal, metodologia |
| P1 | MAPA/WOAH sanidade | febre aftosa, influenza aviaria, PSC/PSA e restricoes | registrar evento, confirmacao, incidencia, geografia, medida oficial e revogacao | alerta nao vira embargo ou perda quantificada |
| P1 | milho, farelo soja, diesel, frete do nucleo NIVON | custos variaveis das tres cadeias | alinhar mesma praca, referencia, qualidade, unidade, prazo | nao converter cotacao em compra executada |

Fontes oficiais para verificacao:
- https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ (1092 / 1093 / 1094)
- https://dados.agricultura.gov.br/pt_BR/dataset/servico-de-inspecao-federal-sif
- https://www.gov.br/agricultura/pt-br/assuntos/inspecao/produtos-animal/sif
- https://www.embrapa.br/en/web/suinos-e-aves/cias/custos/icpsuino
- https://comexstat.mdic.gov.br/
- https://apps.fas.usda.gov/psdonline/

## Modelos futuros, SEM prometer resultados sem series reais

1. **BOVINO**: coortes vaca-matriz/cria/recria/engorda, nascimentos, mortalidade, retencao/descarte de femeas, oferta futura por lag biologico e cenarios de confinamento/pasto. Exigir fontes reais para pesos e eventos sanitarios; evitar transformar PPM anual em rebanho mensal ficticio. Precos boi/bezerro por praca, B3 e spread/reposicao.
2. **FRANGO**: alojamento de pintos, ciclo curto e idade de abate, mortalidade, peso medio, conversao por fase, milho/farelo e capacidade frigorifica. Validar dados primarios de alojamento ou usar somente cenario condicional, nunca estimar plantel com abate de forma determinista.
3. **SUINO**: matrizes/coberturas, partos, desmamados, creche/terminacao, perdas e defasagens especificas, indices tecnicos e exportacoes. Rebanho anual nao e animais disponiveis imediatamente.
4. **MERCADO**: modelos por especie, unidade e praca; sazonal naive, persistencia, regressao com insumos e mercado externo, quantis e classificacao ALTA/BAIXA/ESTAVEL/INDETERMINADA somente apos walk-forward com datas de disponibilidade e dados suficientemente longos. Relatar MAE/RMSE, ganho sobre baseline, cobertura e calibracao; vetar probabilidades sem calibracao externa.
5. **INTEGRACAO**: contratos consumiveis pelo IVO, comercio, mercado e logistica com direitos, fonte, 4 datas (competencia, referencia, publicacao, coleta), unidade, UF/praca, vintage, hash, status observado/inferido/estimado/projetado. Editorial agricola nao deve receber pecuaria automaticamente.

## Gatilhos de homologacao

- Prova de direitos para leitura/coleta/armazenamento/transformacao/redistribuicao por dataset.
- Fixture real com metadados e layout legitimamente permitido, backfill e comprovacao de revisoes.
- Tres extracoes em datas de atualizacao diferentes, persistencia e backup/restauracao, idempotencia, logs.
- Residuos fisicos/biologicos explicados; previsao walk-forward com baseline e nao-leakage.
- Revisor independente e checks CI; sem CI verde e amostra real => CODE_TESTED_SYNTHETIC_ONLY.
- Sem deploy, agendamento, merge, envio WhatsApp, custo ou novos direitos presumidos.

Reproduzir testes sinteticos: PYTHONPATH=src python -m unittest tests.test_pecuaria_ciclos tests.test_pecuaria_mercados
