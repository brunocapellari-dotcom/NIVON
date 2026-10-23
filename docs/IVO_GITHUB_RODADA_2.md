# IVO — Segunda rodada GitHub: histórico, autoavaliação e modelos agroespaciais

Data de referência: 2026-10-20.
Estado: **implementação local offline no PR #7; não homologado para uso real**.
Foco: transformar previsões futuras em resultados verificáveis, alimentar propostas de
melhoria e escolher ferramentas que ampliem conhecimento, previsão e espaço-tempo.

## Pesquisa técnica adicional: biblioteca versus dados

Ferramentas avaliadas e registradas por versão e licença no
`config/ivo_ferramentas_github.v1.json`:

1. **Previsões supervisionadas**: Skforecast (BSD-3-Clause), Darts (Apache-2.0);
   competir com StatsForecast e MLForecast **sem instalar todos no runtime**.
   NeuralForecast (Apache-2.0) somente se backtest real e recursos permitirem.
2. **Qualidade e calibração**: Evidently (Apache-2.0) para monitoramento quando
   o detector simples não bastar; MAPIE (BSD-3-Clause) para intervalos e calibração
   devidamente adaptados à dependência temporal e regimes agrícolas.
3. **Sensoriamento remoto**: PySTAC Client (Apache-2.0) para descoberta,
   ODC-STAC (Apache-2.0) e Xarray (Apache-2.0) para séries espaciais,
   GeoPandas (BSD-3-Clause) e Rasterio (BSD-3-Clause) para geometrias/raster.
   OpenEO client (Apache-2.0) é cliente, **não torna servidor ou imagens gratuitos**.
4. **Explicabilidade e causalidade**: SHAP (MIT) explica contribuição
   de variáveis a um modelo específico, **não prova causalidade**.
   EconML (MIT) exige identificação causal e desenho válido.
5. **Agentes**: Pydantic AI (MIT) pode servir de adaptador tipado, desde que
   não replique funções de Hermes nem permita decisões executivas fora de políticas.
6. **Reutilização**: Hermes já tem proposta -> sandbox -> testes -> benchmark ->
   A/B -> auditoria -> promoção/reversão; IVO precisa integrar-se por contrato.
   Não copiar a implementação inteira nem instalar bases de dados duplicadas.

Licenças de arquivos de código dos repositórios foram lidas via GitHub e estão
indicadas como declaradas; **licenças de modelos treinados, imagens, dados, APIs e
dependências transitivas são questões separadas**. Nenhuma dependência nova foi
instalada. Provedores externos precisam de homologação por operação e limite de
custo comprovado.

## Código novo, sem dependência extra

- `src/nivon/ivo_previsao_ledger.py`:
  - contrato `PrevisaoRegistrada` com modelo, versão, indicador, localização,
    unidade, mês alvo, fonte da verdade, emissão, último instante de disponibilidade,
    registro, previsão, baseline, hash e opcionalmente intervalo.
  - separa `LIVE` (registrado antes do mês-alvo e com relógio real de ingestão)
    de `BACKTEST`; backtest não pode fingir que foi previsão live.
  - observações `ObservacaoPublicada` só são comparadas depois da
    competência mensal encerrada, com fonte da verdade declarada.
  - SQLite guarda inserções idempotentes com conteúdo/hash. Mudança posterior
    requer novo registro/versionamento; sobrescrita por API proibida.
  - preserva vintages por data de publicação e coleta, primeira publicação
    versus última conhecida na data de corte, sem olhar o futuro.
  - avalia MAE, WAPE, viés, desempenho sobre baseline e cobertura do intervalo.
    Restringe médias a **mesmo modelo/versão, indicador, geografia, unidade e
    horizonte**. Métricas não comparáveis não são somadas.
- `src/nivon/ivo_monitor_modelos.py`:
  - compara erros recentes a uma janela histórica da mesma série; um aumento
    relevante ou cobertura baixa gera **alerta para reavaliação**, não retraining
    automático, alteração de versão ou publicação.
  - 'erro em alta' não é sinônimo de drift estatístico nem causalidade.
- `tests/test_ivo_previsao_ledger.py` e `tests/test_ivo_monitor_modelos.py`:
  testes sintéticos de idempotência, revisões, erros, períodos, intervalos,
  desempenho, temporalidade e manutenção do veto à autopromoção.
- `tests/test_ivo_replay_e2e.py`:
  nove meses sintéticos do mesmo modelo, primeiro seis com erro baixo e últimos
  três com erro maior, verificando indicação de reavaliação.
- `.github/workflows/testes.yml`:
  segurança adicional: verificações em PR somente offline; inspeções de
  dados externos e downloads requerem `workflow_dispatch` manual. **Não acionar
  rede externa só para provar que o CI passa**.

## Pontos ainda pendentes

O que está implementado mede previsões fornecidas como entrada; **ainda não
produz ou aprende automaticamente um novo modelo**. A promoção do conhecimento
e treinamento real dependem de:
- séries históricas e vintages autorizados, recebidos em fonte primária e
  conferidos com período, unidade e origem corretos;
- registro durável de dados e features tal como conhecidos no instante previsto;
- backtests walk-forward por cultura, geografia, horizonte e regime;
- modelos candidatos (estatístico, ML, online) contra referência ingênua,
  com métricas de calibração e validação fora da amostra;
- pipeline de conhecimento por Research AI -> Knowledge Factory / Segundo
  Cérebro, sem escrita canônica direta por LLM;
- execução em nuvem com backup/restore, alertas, observabilidade, quota e
  limite de custo previamente homologados.

**Não usar WAPE isoladamente com valores próximos de zero.** Não comparar
previsões de safras, toneladas, reais, cotas de rios ou meses diferentes como
uma única taxa de erro. Intervalos de previsão requerem nível nominal e
calibração próprios; a métrica de cobertura incluída é descritiva e não prova
que o intervalo seja de 80%, 90% ou 95%.

## Exemplo de aplicação final do IVO

"Previu-se chuva insuficiente em julho e risco de atraso de plantio para determinada
região. Os resultados posteriores mostraram que a resposta produtiva ficou fora
do intervalo previsto. Registrar o erro, comparar por tipo de regime e propor,
para avaliação independente, um modelo com índices de solo e balanço hídrico."

É meta futura. O motor atual não alega conhecimento dessa causalidade nem previsão
real, apenas fornece a estrutura para testar a hipótese historicamente.
