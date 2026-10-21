# NIVON — Auditoria da cobertura histórica de fretes por horizonte

**Estado:** ferramenta offline para dimensionar dados históricos, sem coleta live nem habilidade preditiva homologada. Prioridade P0: FRETE_RODOVIARIO.

## Problema corrigido

Uma tendência em 12 **sessões com anúncios** não implica série com 12 dias seguidos, e a comparação de 7, 30 ou 90 **dias corridos** não equivale à avaliação de 7, 30 ou 90 pregões. Uma janela de anúncios com dias vazios, pontos/transportadoras que mudam ou valores de outros terminais pode produzir uma falsa aparência de cobertura preditiva.

A API `nivon.fretes_cobertura_horizontes:auditar_cobertura_horizontes_frete` recebe exclusivamente eventos `OfertaFrete` autorizados e já normalizados pelo chamador; herda os controles do painel pareado R01 (mesmo corredor, terminal, produto, equipamento, pedágio, PF/PJ, fonte e preço BASE BRL/t; repetição e conflito controlados).

## Metodologia

1. Construir índice de ofertas pelo **dia comercial de Mato Grosso**, com data de publicação/coleta anterior ao instante `as_of` e um preço por par `(pickup_entity_id, transportadora_id)` por dia.
2. Para cada horizonte `H = 7, 30, 90` **dias corridos**, só considerar uma origem `D` cuja data-alvo `D+H` já tenha maturado no corte. Alvo no futuro conta como `origens_ainda_nao_maturadas`, jamais como erro da previsão.
3. Se a data `D+H` não existe na série, registrar `origens_sem_alvo_observado`. Não preencher com cotação anterior, média municipal nem preço de outra identidade.
4. Se origem e alvo existem, exigir ao menos dois pares IDÊNTICOS presentes nas duas datas. Se não existir esse painel, registrar `origens_com_pares_insuficientes`. Se existe, contar uma `origem_com_pares_comparaveis`, sem pressupor independência.
5. Produzir contagem de origens e pares comparáveis, exemplos limitados e fingerprint dos SHA das edições **derivadas** nas duas pontas. Esse digest confere só consistência interna relativa aos insumos entregues; **não comprova** autenticidade RAW do anúncio.
6. A mera existência de pelo menos 30 origens comparáveis dá status `ALVOS_HISTORICOS_IDENTIFICADOS_SEM_FORECAST_ARQUIVADO`, não `BACKTEST_OK` nem permissão de previsão. Esse limiar é um pré-voo configurável; não garante suficiência estatística, independência, diversidade sazonal ou segurança de 90 dias.

## Saídas e bloqueios

O relatório contém cobertura por horizonte, `origens_ainda_nao_maturadas`, `origens_sem_alvo_observado`, `origens_com_pares_insuficientes`, `origens_com_pares_comparaveis`, `pares_origem_alvo_total_nao_independentes`, amostras de hash e os flags:

- `calendario_coleta_externo_verificado = false`
- `integridade_raw_comprovada = false`
- `licenca_de_uso_e_redistribuicao_comprovada = false`
- `historico_real_homologado = false`
- `previsoes_arquivadas_validadas = false`
- `backtest_executado = false`
- `probabilidades_calibradas = null`
- `publicavel = false`

Um coletor que não rodou em determinado dia pode ser indistinguível de um dia sem ofertas. Portanto, o **calendário de coleta, a saúde do coletor e a taxa de captura comprovada** deverão ser reconciliados externamente antes de inferir ausência de anúncios e antes de certificar cobertura de mercado.

## Handoff futuro ao motor quantitativo

A auditoria **não fabrica forecasts retrospectivos**. Para avaliar poder preditivo real:

- Persistir previsões datadas **na emissão**, com sua versão de modelo, identidade econômica, preço-base, dados realmente disponíveis até a emissão e hash/âncora independente.
- Depois de maturado o alvo (7, 30 ou 90 dias corridos), reconciliar observação autorizada com a mesma identidade e registrar o preço realizado como observação de anúncio, nunca como preço contratado. Validar a janela temporal e a metodologia para dias sem ofertas.
- Usar os validadores existentes `quant_core` / `auditoria_holdout_quant` e, se necessário, um adaptador explícito de **dias corridos** (não reutilizar um calendário de sessões de bolsa). Não considerar um resultado descritivo sobre dados antigos como previsão emitida no passado.
- Executar avaliação OOS real e holdout purgado, comparar com baseline ingênuo, conferir estabilidade por corredor/safra, regimes, granularidade, custo e autorização de uso. Validar qualidade temporal, cobertura de fontes, estatística e licenças antes de divulgação.

## Testes e execução

`PYTHONPATH=src python -m unittest tests/test_fretes_cobertura_horizontes.py -v` ou `python -m unittest discover -s tests`.

Os testes usam somente eventos construídos artificialmente. O objetivo é comprovar o funcionamento do **contrato de análise de cobertura**, não a existência de históricos reais.

Sem merge, deploy, aquisição de dados ou habilitação de despesas nesta PR.
