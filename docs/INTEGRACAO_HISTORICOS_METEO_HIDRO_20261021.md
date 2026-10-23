# NIVON — Conciliação da biblioteca científica histórica da PR #9
Data: 21/10/2026. Posição: PR filha da consolidação meteo/hidro #68.

## Extração seletiva, sem reintroduzir outros domínios
Cinco módulos e seus cinco arquivos de testes vieram **pelos blobs Git originais** da PR #9:
`noaa_roni.py` (índice retrospectivo de ENSO), `qualidade_cientifica.py` (validações e auditoria de backtesting), `historico_vintages.py` (SQLite de edições point-in-time), `confronto_climatico_qc.py` (INMET × NASA POWER), `analogos_historicos.py` (proximidade de anos análogos).

Os 10 hashes de origem e **duas alterações intencionais** constam em `config/integracao_historicos_meteo_hidro.v1.json`. Os demais componentes setoriais/IA/logística/finanças da PR #9 **não** foram transplantados. A PR #9 permanece draft e terá que ser reconciliada sem duplicar esses módulos.

## Correção crítica de fuga temporal no histórico

`ArmazemVintages.consultar_asof` originalmente selecionava edições apenas por `disponivel_em <= instante_decisao` e `disponibilidade_verificada=1`, **sem confrontar `coletado_em`**. Isso permitia retroagir a um backtest de fevereiro dados cujo arquivo só foi capturado em outubro — mesmo sob aparência de disponibilidade histórica. Os campos e SHA de prova são **declarações externas**, não garantias de que existia uma cópia naquele corte.

Agora a consulta exige cumulativamente `publicado_em <= corte`, `disponivel_em <= corte` e **`coletado_em <= corte`**, além de prova declarada de disponibilidade, sem promover classificação `homologado`. O primeiro instante de coleta de cada edição é preservado; uma nova importação de edição idêntica não poderá torná-la historicamente anterior. Por isso os testes originais desta parte foram corrigidos para usar coletas contemporâneas às publicações e acrescentar casos adversariais com arquivo baixado posteriormente.

### Limites de evidência e dados reais
- O RONI é um **indicador retrospectivo**. O parser mantém publicação desconhecida para cada mês central; a série atual não é feature `as-of` de uma previsão emitida no passado e não pode ser confundida com a MJO/RMM.
- O dataset canônico `NOAA_ENSO_RONI` passou a existir como **CANDIDATE** no catálogo central em 21/10/2026; a rota direta oficial está documentada, porém direitos, preservação de vintages por edição e amostra real no pipeline **continuam pendentes**. **Não foi criado coletor nem fonte habilitada**.
- Confronto INMET–NASA POWER **descreve diferenças estação/grade**, não skill de um modelo prognóstico; não imputar faltantes, não tomar uma célula espacial como medição instrumental.
- Anos análogos são proximidade estatística **descritiva**, não probabilidade, projeção automática de safra ou previsibilidade inferida.
- `historico_vintages` exige arquivo efetivamente coletado na data da decisão para selecionar edições passadas, mas relógios, hashes e evidências autodeclarados ainda requerem auditoria externa. Não existe snapshot real homologado.
- SQLite do laboratório local não substitui guarda imutável de RAW, backup testado, autenticação das fontes, trilhas de coleta e separação de treinamento/validação.

## Testes, critérios e governança
A nova suíte `tests/test_integracao_historicos_meteo_hidro.py` confere os hashes Git originais de arquivos intocados, verifica que as duas mudanças são **explicitamente intencionais**, valida as flags OFF do catálogo/motores e bloqueia alegação de skill com RONI e anos análogos. Os testes de cada módulo upstream permanecem ativos, e `test_historico_vintages.py` ganhou regressões anti-leakage sobre `coletado_em`.

**Critério de aceitação:** GitHub Actions aprovado exatamente no HEAD final, com testes de upstream e regressões contra coleta tardia. Sem alteração em `main`, ativação de fontes ou merge central automático.

## Próximo passo executável
Auditar o ajuste fino de `confronto_climatico_qc` ao calendário físico de 24h INMET e o vintage temporal de grade NASA POWER, após amostras reais legalmente autorizadas; homologar direitos, autenticação de vintage e amostra real para `NOAA_ENSO_RONI` já cadastrado como candidato OFF. Conciliar as demais PRs da #9 em sua própria frente, não pela meteorologia.


## Correção adicional — equivalência física de precipitação diária

Durante a conciliação foi detectado outro risco científico: o agregado INMET de 24 registros rotulados pela data `D` pode cobrir `D-1 às 23h → D às 23h UTC` sob a convenção de **hora como fim do intervalo**, enquanto uma grade diária com a mesma etiqueta `D` pode representar `D às 00h → D+1 às 00h UTC`. Esses números **não** são acumulados do mesmo período e não devem ser comparados por simples igualdade de rótulo.

- Criado `src/nivon/confronto_janelas_fisicas.py:confrontar_chuva_janelas_equivalentes`, que exige para **cada dia** início e fim de intervalo, 24 horas exatas, SHA associado ao dataset correto e referência documental de convenção física. Recusa lacunas, datas duplicadas, fusos ausentes e intervalos distintos. Só após essa conferência chama o confronto descritivo original `confronto_diario_inmet_power`.
- Os **entrypoints registrados** de `CLIMA_HIDRO` e `METEOROLOGIA` agora direcionam exclusivamente ao wrapper de equivalência física; o método original foi mantido para compatibilidade com a PR #9, mas não é ponto de entrada do registro governado.
- `tests/test_confronto_janelas_fisicas.py` executa regressões de 30 e 29 dias, intervalos com 23/25 horas, incompatibilidade INMET fim/NASA início, SHA indevido, datas não pareadas, publicação tardia e QC reprovado.
- A evidência temporal de cada produto ainda é **declarada** no contrato, portanto `evidencias_intervalo_auditadas_externamente=false`, `homologado=false` e `skill_preditiva_comprovada=false` mesmo quando as janelas coincidem.
- O JSON diário original NASA POWER precisa ser enriquecido **somente após fonte, produto, referência espacial, temporalidade e edição serem verificadas**. Não inferir automaticamente UTC civil da etiqueta do arquivo sem consultar a documentação do produto.
