# NIVON — Hidrovias ANTAQ (replica secundaria, 2025)

**Prova E2E:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39948643472  
**Fonte dos Parquet:** https://huggingface.co/datasets/vinicius-souza/antaq, commit `ff0349fa6dc8cebcec161ee3ce48f6f73f7f3ba8` (licenca CC-BY-4.0 declarada por terceiro). Dados derivados, **não fonte oficial**, não frescor assegurado após 18/04/2026.

Arquivos `silver/Carga_Hidrovia/ano=2025/data.parquet`, `silver/Carga/ano=2025/data.parquet`. O código `src/nivon/antaq_replica_detalhe.py` valida unicidade de `IDCarga` em `Carga`, junção por identificador, schema, pesos, classificação SH4 e tipo de navegação. A prova ligou 784.755 registros de trechos hidroviários a 2.464.613 registros de cargas; nenhum trecho ficou sem `IDCarga` correspondente. É **incorreto** somar `ValorMovimentado` de rios diferentes, pois a mesma carga percorre múltiplos rios.

## 2025 — navegação interior, deduplicada por carga

| Classificação | t obtidas | referência ANTAQ aproximada |
|---|---:|---:|
| Total interior `IDCarga` única | 92.431.869,759 | 91.300.000 |
| Soja SH4 1201 | 32.792.953,762 | 31.800.000 |
| Milho SH4 1005 | 20.350.661,291 | 20.200.000 |
| Fertilizantes capítulo 31 | 4.931.879,632 | 4.900.000 |
| Farelo de soja SH4 2304 | 770.053,152 | não conciliado |

**Desvio nacional de +1,24%** em relação ao total oficial arredondado. Somente 53.250.176,855 t das 92.431.869,759 t interiores têm vínculo com a tabela Carga_Hidrovia (~57,61% em tonelagem); não inferir cobertura por hidrovia para os restantes 42,39%. O tipo "Interior" é declaração da réplica, não reconciliação integral com a ANTAQ. Validar revisão/competência/metodologia e possibilidade de cargas faltantes antes de homologar.

## 2025 — exemplos por hidrovia, navegação interior, sem deduplicação entre rios

- Madeira: soja 6.973.417,401 t; milho 3.060.004,434 t.
- Tapajós: soja 7.584.978,210 t; milho 7.271.125,931 t; fertilizantes capítulo 31, 712.947,904 t.
- Baixo Amazonas: soja 10.728.159,507 t; milho 9.293.593,476 t.

Esses recortes são "Desembarcados" na classificação da réplica. Mercadorias por SH4 são agrupadas por código e não constituem inferências sobre uma trading individual.

**Referências oficiais:** ANTAQ 2025 https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/Anuario2025.pdf ; Ministério 2025 Madeira https://www.gov.br/portos-e-aeroportos/pt-br/assuntos/noticias/2026/02/hidrovia-do-madeira-transportou-12-1-milhoes-de-toneladas-em-2025 .

**Status:** fonte secundária auditada com dados reais, mas **não homologada nem gravada no banco GCP**. P0 permanece encontrar descarga oficial ANTAQ em operação e cruzar microdados. Dados do HF não devem sobrescrever a série primária validada.
