# NIVON — Precipitação areal por grade meteorológica e sub-bacia

Data-base: 20/10/2026 · Módulo: `src/nivon/chuva_areal_ensemble.py`.

## Finalidade

O SCS-CN recebe um total de precipitação **representativo da bacia inteira**. Não é fisicamente justificável tomar um único pixel de satélite/grade ou um pluviômetro e tratá-lo automaticamente como a chuva de todo o território. A função `agregar_ensemble_chuva_areal` exige pesos de interseção geográfica entre células da previsão NWP e polígono da bacia, documentados por versão, método GIS e SHA-256.

Para cada instante e membro meteorológico, calcula `P_bacia = Σ (fração_da_bacia_intersectada × chuva_acumulada_mm_celula)`. O peso de cada célula deve ser estritamente positivo, a soma precisa ser exatamente 1 (tolerância numérica de 1e-8), e nenhuma célula ou instante pode faltar. Não normaliza pesos errados, não preenche `-999`/nulos com zero e não aceita duplicação de membro/célula, timezones ausentes nem séries desalinhadas.

A entrada utiliza precipitação **ACUMULADA EM mm POR INTERVALO**, não taxas `mm/h`. Por exemplo, produtos GPM IMERG 30 min geralmente apresentam taxa média mm/h; precisam de conversão explícita `mm/h × 0,5 h` após validar metadados do produto. Fontes: [NASA IMERG directory](https://gpm.nasa.gov/data/directory), [NASA POWER Daily](https://power.larc.nasa.gov/docs/services/api/temporal/daily/).

CHIRPS, IMERG, NASA POWER, ERA5 e estações são observações/estimativas/remoções retrospectivas, não previsões futuras NWP. O parser bloqueia rótulos diretos desses produtos como NWP, mas uma etiqueta textual nunca comprova o conteúdo ou a procedência: origem e data de emissão exigem auditoria externa.

## Integração

A saída de `chuva_areal_ensemble:agregar_ensemble_chuva_areal` é exatamente o contrato `membros_chuva` esperado por `ensemble_hidrologico_bacia:cenario_ensemble_bacia`: membros com chuva areal futura para cada horário. O segundo motor aplica SCS-CN ao acumulado do evento e transforma os excedentes em vazão direta usando hidrograma unitário externo.

O fluxo integrado foi testado com 2 células × 3 membros e conservação volumétrica por membro. A precisão NÃO foi avaliada com dados reais. Não existe polygonização, reprojeção ou cálculo automático de frações GIS neste módulo — esses pesos dependem de um processo externo auditável. O campo `intersecao_gis_auditada_externamente` permanece `false`.

## Restrições de produção

- Não confundir chuva histórica/estimada com previsão meteorológica.
- Não chamar fração de membros de probabilidade calibrada.
- Não deduzir cota de rio, risco de cheia, navegabilidade ou ETA de barcaça da vazão direta.
- Calibrar hidrogramas e solos da bacia com dados ANA/INMET e validar fora da amostra.
- Nenhum módulo aciona HTTP, publicação, automação, deploy ou altera observações canônicas.
