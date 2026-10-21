# NIVON — Ensemble de chuva convertido em cenários de vazão direta

**Implementado em 20/10/2026.** Componente: `nivon.ensemble_hidrologico_bacia:cenario_ensemble_bacia`. Testes: `test_ensemble_hidrologico_bacia.py`.

## Contrato operacional e matemático

A entrada aceita 3 a 200 membros meteorológicos, TODOS identificados e com o mesmo horizonte em UTC e timestamps posteriores à emissão da previsão. `dados_publicados_ate` não pode ser posterior ao instante de emissão. Os valores recebidos precisam representar **chuva acumulada por intervalo sobre a área da sub-bacia** (não a precipitação de um único pluviômetro arbitrário).

Para cada membro:
1. Acumular precipitação ao longo de um mesmo evento e aplicar SCS-CN ao TOTAL acumulado — não repetir abstração inicial de chuva para cada passo.
2. Produzir incrementos não negativos de chuva excedente e convolvê-los com um hidrograma unitário fornecido/calibrado de pesos não negativos que somam 1.
3. Preservar a cauda de recessão e auditar conservação do volume [1 mm × 1 km² = 1.000 m³].
4. Calcular pico e volume de **vazão direta modelada** e horário UTC do pico.

Agregação de ensemble: quantis p10/p50/p90 de pico e volume, pico médio e FRAÇÃO de membros com pico acima ou igual a um **limiar de vazão direta** explicitamente fornecido. Quantis usam interpolação linear nos membros ordenados. Se todos os membros forem idênticos, o status é `SEM_DISPERSAO_IDENTIFICADA`, não um intervalo confiável de incerteza.

## Gate científico — interpretação

Fração do ensemble **não é probabilidade calibrada de cheia**; o limiar de escoamento direto não é cota de rio nem nível crítico da Defesa Civil. A vazão direta de uma sub-bacia exclui vazão de base, captações, afluentes, roteamento fluvial e variação de curva-chave. Sem chuva prevista já emitida em um serviço autorizado, parâmetros físicos calibrados e hidrogramas aferidos, os resultados são cenários sintéticos condicionais, e o Ivo **não poderá comunicá-los como previsão operacional**.

Para evoluir: catálogo georreferenciado de bacias/estações e sua conectividade; mapeamento das grades e pesos areais; dados históricos ANA/INMET e previsões meteorológicas com vintages; calibração SCS-CN/transformação e roteamento; comparação probabilística por horizontes usando CRPS/Brier/NSE; validação temporal e espacial e auditoria independente.

O módulo não executa rede, não dispara alertas, não modifica fonte observada, não habilita automação ou deploy.
