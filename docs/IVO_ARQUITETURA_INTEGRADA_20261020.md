# IVO — arquitetura integrada e auditoria incremental (20/10/2026)

**Estado: CODE_ONLY, OFFLINE, NÃO HOMOLOGADO.** Branch empilhada sobre PR #7; PR #13 continua responsável por integração transversal das 14 frentes. Sem deploy, merge, coleta, modelo remoto, treino real, credenciais ou custos.

## Auditoria do código acessível

- NIVON `main`: README apenas; motores e coletores estão em branches/PRs draft.
- PR #7: `ivo_planejador`, `ivo_conhecimento_adapter`, `ivo_elegibilidade_rotulos`, `ivo_previsao_ledger`, bridges CONAB/ANA/INMET e laboratórios temporais. **Reutilizar, não reimplementar**.
- Hermes AI: `context_fabric`, `authorization`, `approval`, `self_improvement`, `routing`, `runtime_memory` e `evaluation` existem em código; integração autenticada NIVON→Hermes ainda precisa de prova E2E.
- Research AI: pesquisa, `RESEARCH_PACKAGE` e Knowledge Factory; serviço central, não um segundo pesquisador autônomo dentro do IVO.
- Second Brain: claims canônicos validados, supersession e grafo derivado; somente leitura pelo IVO.

## Uma arquitetura, sem agentes redundantes

```text
Usuário/API autenticada
  → Hermes (políticas, orquestração, contexto, memória segregada, telemetria)
  → IVO (interpretação agro, seleção de frentes e pacote de evidências)
    → Dados NIVON e snapshots as-of (licença, quatro datas, versões)
    → Segundo Cérebro (claims aprovados, somente leitura)
    → Research AI (pesquisa e verificações, sem promoção direta)
    → Motores quantitativos especializados (forecast avaliado, quando homologado)
  → Auditor independente
  → Resposta citada e limitada OU abstenção
```

O modelo de linguagem nunca é calculadora, gerador de probabilidades fictícias ou autoridade para ferramentas. IVO não cria segundo runtime ou memória paralela do Hermes.

## Código entregue nesta branch

`src/nivon/ivo_pacote_evidencias.py` compõe leitura do planejador e do recuperador lexical já existentes. Recebe identidade `tenant/projeto/ator` e corte temporal do servidor. Exige callback confiável de autorização **por claim, fonte e operação** antes de expor a evidência. Se não houver callback, o retorno for diferente de `True` ou ocorrer falha, nega. Status ou direito meramente declarado no snapshot nunca bastam.

Preserva identificador, texto não confiável, URL, fonte, SHA do documento, competência, natureza, data de referência, publicação, coleta, validação e auditoria. Retorna hash determinístico do manifesto e abstenção explícita quando não há material autorizado.

Divergência numérica é apenas **sinal** calculado sobre fatos estruturados com mesmo indicador, local, competência/safra, unidade, natureza e instante de referência, sem extração numérica de texto ou inferência causal. Fatos estruturados ainda exigem atestação externa.

**Atenção:** callback injetável NÃO é autenticação criptográfica. Precisa ser criado e verificado por um gateway server-side autenticado, com claims de identidade não controlados pelo usuário/LLM, direitos por operação e trilha auditável. O pacote não prova a autoridade do callback nem a verdade dos fatos.

## Decisão de frameworks e pesquisa upstream

| Upstream | Decisão | Condição |
|---|---|---|
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | ADOPT via Hermes | Ferramentas tipadas, human-in-the-loop, persistence; **não instalar runtime IVO separado** |
| [LangGraph](https://github.com/langchain-ai/langgraph) | BENCHMARK | Checkpointing/execução durável; sobrepõe recursos Hermes |
| [LlamaIndex](https://github.com/run-llama/llama_index) | RESERVE | RAG híbrido/semântico somente com benchmark de precisão, datas e citações |
| [DuckDB](https://github.com/duckdb/duckdb) | OPTIONAL EXISTENTE | Adaptador Parquet as-of já na PR #7 |
| [MLForecast](https://github.com/Nixtla/mlforecast), [River](https://github.com/online-ml/river) | OPTIONAL EXISTENTE | Benchmarks de séries e replay prequential; rótulos reais não homologados |
| [OpenTelemetry](https://github.com/open-telemetry/opentelemetry-python) | ADOPT via Hermes | Traces sem segredos, conforme orçamento e privacidade |
| [OWASP GenAI Security](https://genai.owasp.org/) | REFERÊNCIA | Prompt injection, privilege escalation, exfiltração, auditoria adversarial |

Licença do código não autoriza automaticamente modelos, dados, APIs ou redistribuição. Nenhum código upstream incorporado nesta alteração.

## Gates e próximos testes E2E

1. Conectar autenticação/autorização efetiva Hermes ao gateway NIVON, com tenant, recurso, operação e budget; provar isolação com testes adversariais.
2. Reconciliar fontes licenciadas, snapshots e Knowledge Factory/Segundo Cérebro (assinaturas, direitos, metadados e supersession); não escrever memória canônica automaticamente.
3. Executar consultas reais somente leitura, com regressões de abstenção/citação/temporalidade e defesa contra prompt injection.
4. Invocar motores quantitativos **homologados**, exigir horizonte, unidade, erro histórico, intervalo, fonte, versão e label certificado; jamais converter anúncio/programação em realizado.
5. Avaliar walk-forward, leakage, drift, precisão factual, recall/citação, custo, uso indevido de ferramentas e revisões independentes.
6. Consolidar as 14 branches sob coordenação PR #13, rodar CI no SHA integrado, auditar e homologar antes de merge/deploy.

**Evidência limitada:** testes desta branch usam fixtures sintéticas, não são prova de modelo funcional nem de operação real.
