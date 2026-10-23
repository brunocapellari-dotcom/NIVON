# NIVON — Base Quantitativa Compartilhada (primeira entrega)

**Base de desenvolvimento:** feat/motor-tendencias-transversal-20261020 (PR #12).  
**Situação:** código offline e ensaios sintéticos; NÃO HOMOLOGADO, sem merge nem deploy.

## Auditoria e priorização

- **P0:** fretes anunciados por corredor + estabelecimento/lote econômico, CBOT/CME por vencimento/tipo e preço físico por praça e produto. Respeitar a proibição de média municipal de fretes nos relatórios e não tratar anúncios como contratos.
- O motor existente motor_tendencias.py usa Theil–Sen e comparações YoY **descritivas**; os cenários ponderados explicitamente não são probabilidades.
- previsoes.py possui walk-forward CAGR limitado a séries anuais; previsoes_bibliotecas.py oferece backtest mensal com baseline sazonal, porém espera dados já selecionados as-of; qualidade_cientifica.py e validacao_previsoes_ambientais.py têm auditorias de previsões com contratos diferentes.
- Falta um provedor único de calendários de pregão confiáveis e séries versionadas; datas diárias não provam fechamento antes de uma emissão intradiária. Dados reais, direitos, point-in-time, sobrevivência de metodologias e holdout externo não foram auditados.
- Há risco de falso skill quando scores de teste sintético ou pseudo-OOS são promovidos a previsão calibrada. Não fazer isso.

## Inventario verificavel do manifesto de motores (PR #12)

O arquivo config/motores_inteligencia.v1.json registra **28 frentes de dominio, 270 vinculacoes, 120 entrypoints distintos em 54 modulos e 288 indicadores planejados**. O registro bloqueia operacao e previsao homologada em todas as frentes. Essas contagens nao sao modelos estatisticos distintos nem dados realmente alimentados.

**Bloqueio P0 especifico:** tendencias_mercados.py/tendencia_frete_anunciado aceita agregacao por municipio/corredor sem identidade obrigatoria do estabelecimento, transportadora, descarga e regime. A mediana de lotes distintos nao deve substituir comparacao do mesmo estabelecimento em condicoes equivalentes. Issue #25 documenta correcao setorial com testes. Nao calcular medias municipais de frete.

## Contratos adicionados

Arquivo src/nivon/quant_core.py, **sem dependências externas**. Numeros nao finitos, erros/metrica em overflow, identificadores misturados e intervalo incompleto causam falha:

1. preparar_folds_asof: seleciona para cada origem exclusivamente a edição observacional cujo timestamp de publicação E coleta precede a emissão; exige também serie_id, unidade e fonte_id homogeneos. Falha com falta de dado ou edição ambígua. Recebe calendário de sessões/competências fornecido pelo módulo setorial. Só entrega fold de avaliação, sem chamar modelo ou acessar rede.
2. avaliar_previsoes_oos: exige série, modelo, unidade, baseline e horizonte constantes, identidade exata da origem/alvo no calendário, timestamp com fuso para feature, treino, emissão, publicação e coleta do observado, além de SHA de edição. Devolve MAE, RMSE, viés, baseline, ganho relativo quando definido, acerto direcional (banda explícita), Brier multiclasse, bins de confiabilidade e cobertura/largura dos intervalos quando fornecidos. Brier = média de 3 erros quadráticos (não soma), logo só comparar scores com a mesma convenção.
3. tendencia_empirica_oos: produz frequência preditiva suavizada de ALTA/ESTABILIDADE/BAIXA propagando os erros históricos declarados OOS do MESMO modelo/série/unidade/horizonte para a previsão nova. Exige 30 resíduos com resultado publicado **antes da nova emissão** e impede misturar segmentos. **Não chama essa frequência de calibrada.** A hipótese de estabilidade dos resíduos entre regimes ainda precisa ser testada.

### Exemplo de uso (não operacional)

```python
from nivon.quant_core import avaliar_previsoes_oos
resultado = avaliar_previsoes_oos(
    arquivo_previsoes, calendario=calendario_oficial,
    serie_id="CBOT_SOJA_NOV26", modelo_id="ETS_V1",
    unidade="USC/BU", baseline_id="PERSISTENCIA",
    horizonte_periodos=5, as_of_avaliacao="2026-10-20T20:00:00Z",
    tolerancia_absoluta=3.0,
)
assert resultado["publicavel"] is False
```

## Escopo matemático, limites e critérios

- Os módulos setoriais são donos de seus modelos, séries, filtros e parâmetros. A equipe quantitativa é dona do contrato e da validação transversal; não duplicar coletores.
- O horizonte é número de períodos **do calendário enviado**, não número presumido de dias. Pregões CME/ICE requerem calendário oficial com feriados e validação independente de fechamento e ajuste; calendário de teste é apenas sintético.
- Dados intradiários: sempre timezone-aware. Provas de vintages exigem logs brutos imutáveis, hashes e publicação verificada; a função valida metadados declarados, não sua autenticidade.
- O valor-base, observado, previsto, benchmark e intervalo devem possuir a MESMA unidade física/econômica. Frete BRL/T não pode ser combinado com frete de unidade/convenção diferente; CBOT USC/BU não equivale a USD/T. Não usar média municipal de fretes.
- Brier não calibrado não vira probabilidade confiável; exigir testes de confiabilidade, skill de baseline, amostra suficiente, separação treino/calibração/teste, análise por regime e horizonte, bloqueio de leakage e controle de múltiplas comparações.
- Folds próximos num horizonte longo têm labels/resíduos sobrepostos; não aplicar intervalos de confiança iid nem calcular significância sem correção por autocorrelação.
- Se o modelo não superar benchmarks ou não provar vintage as-of: INDETERMINADA / SEM PREVISÃO HOMOLOGADA. Nenhuma API desta entrega autoriza forecast público.
- Para produção: dataset licenciado point-in-time, calendário curado, lineage, treino reexecutado por vintage, backtest rolling-origin estrito, holdout temporal/espacial, reconciliação com PR #13, CI no SHA integrado e autorização humana de deploy.

## Execução local

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_quant_core.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

**Limite:** nenhum desses testes sintéticos é evidência de previsibilidade de frete, preço físico ou CME. 

## Ciclo seguinte — runner rolling-origin com previsão estritamente ex-ante (20/10/2026)

`src/nivon/rolling_origin.py` acrescenta `executar_rolling_origin_asof`, usando
o preparador as-of e **reestimando/chamando o modelo separadamente para cada origem**.
O callback recebe exclusivamente uma tupla imutável de observações históricas e contexto
imutável contendo origem, emissão, alvo e horizonte. O observado do alvo não é passado
ao callback: só é adicionado **após** seu retorno ao arquivo de avaliação.

O baseline implementado é `PERSISTENCIA_ASOF` (último valor conhecido naquele
corte), por indicador homogêneo; a mesma auditoria `avaliar_previsoes_oos` executa
as métricas OOS. O runner não instala dependências, não chama coletores nem altera
os adaptadores comerciais. Forecasts podem retornar ponto, bandas/intervalos e
probabilidades com schema restrito; scores são calculados depois do resultado real.

**Atenção:** a função modelo fornecida é código Python arbitrário, podendo consultar
globais e serviços externos; a biblioteca só impede vazamento **por argumentos**
do callback. Não há sandbox de execução: provar ausência de leakage requer code
review e execução isolada. Não usar um callback que consulta o arquivo integral.
Backtest com vintages reconstituídos não demonstra que as edições estavam
realmente acessíveis historicamente: exigem-se logs brutos/SHAs e origem verificável.

### Exemplo de teste sintético do runner

```python
from nivon.rolling_origin import executar_rolling_origin_asof
def persistencia(treino, ctx):
    return treino[-1]["valor"]  # sem acesso ao resultado futuro
resultado = executar_rolling_origin_asof(
    observacoes=arquivo_vintages, calendario=calendario_curado,
    origens_em=origens_com_timestamp, as_of_avaliacao="2026-10-20T20:00:00Z",
    serie_id="CBOT_SOJA_NOV26", unidade="USC/BU", fonte_id="FONTE_CURADA",
    modelo_id="PERSISTENCIA_V1", horizonte_periodos=5, tamanho_treino=30,
    modelo=persistencia, min_folds=10, tolerancia_absoluta=3.0,
)
assert resultado["publicavel"] is False
```

A frente de Mercados desenvolve `validacao_tendencias_mercado.py` em branch
separada, já com benchmark probabilístico expansivo. Ela deverá ser **conciliada**
por contrato e convenção de Brier: `quant_core` usa soma/3 e o validador setorial
usa soma pura. Ambas as métricas são válidas, porém não numericamente
comparáveis sem multiplicar/dividir por três. Não criar pipelines paralelos de calibração.

A frente de Logística possui `fretes_registros.py` com
`pickup_entity_id`, `transportadora_id`, `descarga_entity_id` e
regime PF/PJ; sua estrutura deverá alimentar filtros de séries equivalentes.
Issue #25 permanece até correção efetiva do adaptador de tendências.

### Gate adicional de aceitação

- CI no SHA final contendo runner e testes adversariais, sem afirmar skill com
  dados sintéticos;
- calendários de pregão/feriados e vintages de fontes autorizadas;
- avaliar modelos com treinamento que não lê labels futuros, janelas de calibração
  separadas e holdout temporal não reutilizado na escolha de modelo;
- comparar baselines por série/horizonte/regime, auditar métricas probabilísticas,
  amostra efetiva e dependência temporal, e bloquear previsão em caso de degradação.
