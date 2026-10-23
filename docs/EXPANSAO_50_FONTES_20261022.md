# Expansão NIVON — 50 recursos (22/10/2026)

## Escopo verificável
- **40 novas fontes e 40 datasets** foram registrados no catálogo canônico `config/fontes_nivon_master.v1.json`.
- **40 rotas** de coleta foram geradas em `config/rotas_coleta.v1.json` para planejamento e diagnóstico, todos em `runtime_enabled=false` e `scheduled_enabled=false`.
- **10 projetos GitHub** foram registrados em `config/motores_externos_20261022.v1.json`. Não são API nem foram instalados; licenças, segurança, benchmark e compatibilidade aguardam revisão.
- `src/nivon/fontes_expansao_20261022.py` oferece inventário dos 40 contratos e amostra limitada de metadados para **CCEE (CKAN PLD_HORARIO)**, **BCRA (Monetarias v4)** e **USDA MyMarketNews (catálogo reports; exige chave)**.
- **37 fontes ainda não possuem endpoint final e parser validado**; não fingir que "conector" é coleta operacional. As três rotas são executadas apenas por chamada explícita, sem agendamento, sem persistência nem publicação.
- Testes offline: `python -m unittest tests.test_fontes_expansao_20261022 -v` (testes de contrato e HTTP simulado). Resultados reais devem ser reportados separadamente.

## Sequência de homologação
1. Descobrir endpoint/URL de arquivo oficial por dataset com versão e proveniência. Publicação em portal não implica permissão automatizada.
2. Validar licença de coleta, armazenamento, uso não comercial e atribuição de cada fonte. Manter autorização isolada por operação.
3. Implementar parser tipado, esquema canônico com competência/referência/publicação/coleta e qualidade, sem inferir observação a partir de previsão.
4. Rodar smoke HTTP real limitado; guardar snapshot bruto sob chave/hash e comparar schema/frescor/histórico.
5. Persistência idempotente com watermark; backfill histórico permitido; depois reconciliação com pipelines de preços, safras, logística e clima.
6. Ligar escalonamento somente para fonte homologada, com volume/custo controlados e métricas operacionais.
7. Avaliar as 10 bibliotecas open source; preferir adaptação isolada em vez de instalar todas.

## Pontos de atenção
- SIO Granos tem portal e recursos de consulta, mas contrato de API ainda precisa validação por endpoint.
- BCRA: não usar versões antigas de /principalesvariables; utilizar API monetária v4.
- USDA MyMarketNews requer cadastro/chave pessoal, armazenada em Secret/variável de ambiente; nunca commit.
- CCEE: pacote CKAN fornece lista de recursos, não cotação pronta; exigir parser e datas antes de alimentar preço da energia.
- Plataformas como INDEC e GRDC podem exigir cadastro/termos específicos.
- Preços de produtos em reais, pesos, dólar/ton, ATR e outras unidades nunca devem ser somados ou comparados sem conversão explícita e data de câmbio.
- Histórico de áreas, produção ou fluxos modelados não é execução comercial nem transporte realizado.

## Critério de aceite por dataset
Fonte identificada -> endpoint resolvido -> licença/limite verificados -> schema documentado -> amostra real com SHA -> parser robusto -> backfill -> persistência idempotente -> monitoramento e operação homologados.
