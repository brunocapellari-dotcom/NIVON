# NIVON — Motor hidrometeorológico: cenários, calibração e auditoria

**Atualização:** 20/10/2026 · **PR #1** · Implementação offline, sem previsão operacional homologada.

## Motor meteorológico probabilístico

`src/nivon/meteorologia_probabilistica.py` calcula:
- **Brier Score**, Brier Skill contra probabilidade climatológica definida por época e local, e frequências observadas em 10 classes de probabilidade.
- **CRPS de ensemble empírico**: `1/N Σ |x_i−y| − 1/(2N²) Σ_i Σ_j |x_i−x_j|`. Não aplicar correção *fair* silenciosamente; quantidade de membros deve ser constante no conjunto avaliado.
- Média da dispersão entre membros, amostra ≥30 por local/variável/horizonte, sem aprovar bins com menos de 10 ocorrências como boa calibração.
- Emissão anterior à validade, features publicadas antes da emissão e QC aprovado. A etiqueta `FORA_AMOSTRA` do caller não comprova por si só que o treinamento não teve contaminação.

Referência de metodologia: [WMO — Guidelines on the Verification of Hydrological Forecasts](https://wmo.int/media/news/wmo-issues-guidelines-verification-of-hydrological-forecasts). A verificação deve separar confiabilidade, viés, habilidade contra baseline e habilidade em eventos extremos. A probabilidade é especificada por limiar e horizonte, nunca fabricada por LLM.

## Bacia: chuva → perdas → vazão direta

`src/nivon/hidrograma_bacia.py` aplica CN de evento à **chuva AREAL ACUMULADA**. A diferença do escoamento acumulado forma a chuva excedente incremental. Nunca aplicar CN a cada hora isoladamente, o que reaplicaria indevidamente a abstração inicial. A unidade hidrograma, fornecida e calibrada para a bacia, é uma distribuição não negativa de volume que soma 1. O produto `mm * km² * 1.000` gera m³ e a convolução com esse kernel determina m³/s por passo temporal.

O algoritmo carrega a cauda completa do escoamento e verifica conservação de massa. Não calcula vazão de base, remanso, afluentes laterais, calado ou hidrovia. Não é a curva paramétrica SCS do HEC-HMS: **o kernel de UH é externo e exige calibração documentada**. Veja [HEC-HMS Unit Hydrograph](https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/transform/scs-unit-hydrograph-model).

A saída da unidade de sub-bacia pode seguir ao módulo `hidrologia_chuva_vazao:propagar_muskingum` depois da adição explícita das entradas laterais e calibração do trecho. O controle volumétrico deve considerar armazenamento final e não apagar fluxos para forçar fechamento.

## Calibração de parâmetros por bacia

`src/nivon/calibracao_cn_bacias.py` seleciona CN da grade informada **somente** pelos eventos anteriores ao corte e publicados até o corte. Mede desempenho no holdout posterior, compara RMSE, MAE, NSE e skill contra a média do treino. Eventos históricos com chuva publicada depois do corte não entram no treinamento, mesmo que a chuva tenha ocorrido antes.

Este é um teste de **ajuste retrospectivo com precipitação observada**. Não prova que o modelo pode prever eventos usando chuva futura. Para forecast verdadeiro ainda será necessário usar saídas meteorológicas emitidas antes do evento, considerar incerteza de chuva, solo/ocupação, CN variável e calibração espacial independente.

## Integração Ivo

- Ivo recebe valores **observados**, **estimados por grade**, **modelados**, **projetados** e **não homologados** como classes distintas.
- Só pode comunicar probabilidade de chuva ou vazão quando houver modelo com backtest por horizonte, qualidade e amplitude de incerteza verificadas. Nunca converter CN, CRPS ou score favorável em garantia de enchente ou produtividade.
- Para BR-163, Miritituba, Tapajós, Teles Pires, Juruena, Rio Paraguai e demais corredores, traduzir sinais hidrológicos para logística somente com cotas oficiais, datum/trecho, profundidade/batimetria e alertas das autoridades competentes. Sem isso o sinal é apenas **condicional**.

## Gates para homologação

1. Ingerir séries autorizadas ANA, INMET, NASA e CHIRPS, preservando versão, datas de competência/publicação/coleta e QA.
2. Mapear estações, bacias, sub-bacias, área e gradação de chuva (pluviômetro vs grade, CRS, local, altitude).
3. Calibrar parâmetros no histórico observado sem look-ahead e validar em holdout temporal **e espacial**.
4. Comparar ensemble meteorológico e modelos hidrológicos contra climatologia, persistência e estações observadas; auditar sazonalidade e extremos.
5. Registrar intervalo de confiança e política de decisão. Promover apenas mediante auditoria humana com evidência.
6. Prover storage durável, backup-restauração, observabilidade, agendamento permitido e licenças verificadas.

**Não executa monitoramento contínuo, rede ou deploy; resultados sintéticos não autorizam alerta operacional.**
