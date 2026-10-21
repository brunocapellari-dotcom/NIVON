# NIVON — Camadas meteorológicas e MJO (20/10/2026)

**Estado:** implementação local de parser MJO em PR isolado, sem coletor ativo, treinamento, mapas publicados ou deploy. A aparência de produtos comerciais é apenas referência funcional; não copiar interface, dados ou imagens.

## Evidências visuais e arquitetura

1. **Estações** — camada de pontos por temperatura (instantânea, Tmax, Tmin), umidade, precipitação em janelas de 1/3/7/30 dias, vento/rajadas, pressão, radiação. Integrar redes somente conforme direitos e atribuição. Mostrar horário da última observação, provedor, QC e localização; não tratar 1000 estações como 1000 municípios.
2. **Radar + GOES-19** — camadas de visualização e nowcasting com distinção entre reflectividade de radar, raios (GLM), imagem infravermelha, visível, estimativa satelital de chuva e acumulação pluviométrica. Ausência de radar não equivale a ausência de chuva. Produtos CPTEC/INPE apresentados em seus portais têm restrições explícitas de reprodução e comercialização; não replicá-los sem autorização.
3. **Anomalias e risco agroclimático** — clima observado por estação/reanálise (e sua incerteza) confrontado contra normals históricas da MESMA época e janela. Alertas de geada, seca e encharcamento dependem de limiares agronômicos validados para cultura, fase, município e cobertura de estações.
4. **Modelos e previsão** — GFS/GEFS, ECMWF IFS/AIFS open data, CPTEC, com run/valid time, ensemble members, resolução, vintage, status e direitos explícitos. Camada probabilística deve ser calibrada com Brier/CRPS e baselines e ter testes fora de amostra.
5. **MJO** — primeira entrega desta PR é `src/nivon/mjo_rmm.py`: leitura offline de arquivos no formato RMM/BOM fornecidos ao processo (não há coleta). Não troca fase calculada no provedor por uma fase inventada. Confere magnitude sqrt(RMM1²+RMM2²), rejeita sentinelas, datas incoerentes e força publicação/captura conhecidas para consulta `as-of`. Dados baixados hoje NÃO permitem simular o que a aplicação sabia anos atrás. Não mistura o índice RMM de Wheeler-Hendon com o CPC/EEOF de 10 índices.

## Fontes candidatas a estudar / homologar

| Origem | Papel | Observação |
|---|---|---|
| BOM RMM | História e fase/amplitude MJO | https://www.bom.gov.au/climate/mjo/index.shtml — avaliar termos/direitos |
| NOAA CPC RMM | Índice/forecast MJO (metodologia RMM; diferenças sutis BOM/CPC) | https://cpc.ncep.noaa.gov/products/precip/CWlink/MJO/whindex.shtml |
| NOAA/PSL MJO | Índices alternativos, pesquisa e séries | https://psl.noaa.gov/mjo/mjoindex/ |
| INMET | Observações estações e históricos | exige parser/licenças/rotas operacionais testadas |
| ANA | Chuva e telemetria (hidrologia) | acesso oficial HidroWebService exige homologação |
| NASA GPM IMERG / CHIRPS | Chuva por grade, diferentes latências e resoluções | não é pluviômetro |
| NASA POWER / Copernicus ERA5-Land | Variáveis históricas por grade/reanálise | não é medição de estação |
| ECMWF Open Data | IFS/AIFS forecast aberto CC BY 4.0 | https://www.ecmwf.int/en/forecasts/datasets/open-data-0 — ver termos |
| INPE CPTEC DSAT | Radar/satélite GOES-19 como referência | https://www.cptec.inpe.br/dsat/ — restrição à reprodução comercial |
| Sigma Meteorologia | Referência UX/nowcasting, não coletor aprovado | https://sigmameteorologia.com/nowcasting/ — licença a validar |

## Regras meteorológicas do Ivo

- Fase e amplitude RMM são **índices derivados** de observações; não são probabilidade municipal de chuva.
- Em RMM com amplitude menor que 1, classificar sinal como fraco; não emitir previsão regional a partir da fase.
- Antes de gerar probabilidades de anomalia de chuva por MJO, exigir hindcast municipal/estacional, controle de ENSO/sazonalidade, efeitos espaciais, amostra e incerteza. Usar como variável adicional, não como previsão determinística.
- **Vintages:** histórico retrospectivo obtido hoje é inadequado para reproduzir disponibilidade passada; coleções de runs/snapshots com timestamp comprovado são necessárias para validação as-of.
- Mapas de estações, alertas e mensagens WhatsApp somente com coletores homologados, camada de licenças aprovada, infraestrutura e backup confirmados.
- CI sintético não implica go-live.

## Critérios de aceitação futuros

1. Registrar matriz de cobertura por estado/município, estação e produto; medir atrasos, erros, duplicatas e missing data.
2. Para mapas, validar projeção, escala de cores, clusters, unidade, legenda, horários, atualização e fonte. Proibir interpolação de observações escassas como medição direta.
3. Para MJO, integrar atualização via coletor com limites e licença revisados, catálogo do NIVON, temporalidade, série histórica e UI de diagrama de fases; validar comparações com dados oficiais.
4. Para modelos, validar skills por região e época, lead-time, eventos extremos e independência espacial/temporal.
5. Não habilitar monitoramento, deploy, scheduler ou alertas antes de homologação real e segurança.
