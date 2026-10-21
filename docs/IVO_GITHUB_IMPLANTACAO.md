# IVO: pesquisa GitHub, utilidade e implantação com governança

Data de referência: 2026-10-19.
**Estado: componente de planejamento offline e testes; nenhuma inteligência autônoma em produção.**

## Papel do IVO

IVO é um coordenador cognitivo especializado no agronegócio. O NIVON mantém dados e motores de produção, pecuária, indústria, mercados, hidrologia, meteorologia, logística, comércio exterior, energia e geopolítica. IVO combina esses domínios para perguntas práticas, pesquisa, alerta, explicação e planejamento de previsões, mas não substitui os motores setoriais ou o Hermes.

Exemplos de perguntas que deverá responder após o go-live:
- Como um atraso do plantio da soja no norte de MT altera risco de janela do milho safrinha, disponibilidade de transporte e exportação?
- Como seca, diesel, câmbio, prêmio e line-up alteram a paridade e a pressão de frete Sorriso–Rondonópolis e Sinop–Miritituba?
- Como demanda de farelo, custo do milho e exportações afetam a dinâmica de frango e suínos?
- Quais fatores históricos antecederam períodos de baixa vazão e restrição de calado, e que evidência apoia o cenário atual?
- A previsão histórica do IVO teria antecipado determinada alta de preços usando apenas informações já públicas naquela data?

**A resposta operacional futura deverá conter** fonte primária, safra/ano civil, localidade, unidade, quatro datas, versão, observação versus inferência, cenários, erros históricos, intervalos e fatores não identificáveis.

## O que foi implementado agora

- `src/nivon/ivo_planejador.py` consulta a matriz de 28 frentes, os motores e as fontes do NIVON. Identifica termos de culturas/domínios, seleciona frentes complementares, indicadores e riscos, exibe as dependências e direitos, preservando status de coleta e previsão não homologados. Não executa código de motor, coleta, rede, LLM ou previsão; não altera arquivos.
- `src/nivon/ivo_console.py` expõe leitura do plano via JSON (sem endpoint público):
  `PYTHONPATH=src python -m nivon.ivo_console --pergunta "O atraso das chuvas pode afetar soja e fretes?"`
- `src/nivon/ivo_aprendizado.py` aplica filtros iniciais a candidatos de conhecimento e folds de backtest, sem promoção automática.
- `config/ivo_ferramentas_github.v1.json` registra projetos selecionados, licença declarada, prioridade, finalidade, situação e bloqueios de implementação.
- Testes automatizados: `tests/test_ivo_aprendizado.py`, `tests/test_ivo_planejador.py` e `tests/test_ivo_console.py`.

O roteador é **lexical**: não interpreta genericamente todas as intenções do usuário; não o confundir com um chatbot final. Toda saída é um plano. A interface conversacional com LLM dependerá de um adaptador de modelo autorizado e observabilidade.

## Pesquisa e decisões técnicas

| Projeto | Função e decisão | Consideração |
|---|---|---|
| Nixtla StatsForecast | **Reutilizar** adaptador opcional já presente em `previsoes_bibliotecas.py` | Modelos estatísticos, sazonalidade, previsão probabilística; provar acurácia em dado real |
| Nixtla MLForecast | **Candidato P0** | Modelos supervisionados com features de lags e covariáveis; requer time splits e disponibilidade histórica rigorosa |
| River | **Candidato P0** | Aprendizado online/prequential e drift; não aprender com o rótulo antes de sua publicação |
| DuckDB | **Candidato P0** | SQL analítico sobre históricos, snapshots e Parquet; sem necessidade de serviço permanente, mas persistência/backup na nuvem continuam necessários |
| NetworkX | **Candidato P1** | Grafo de eventos e hipóteses; aresta não demonstra causalidade |
| LlamaIndex Core | **Candidato P1** | RAG, recuperação e citações; auditar todos os plugins e custos de embeddings/LLM |
| MLflow | **Candidato P1** | Registro de experimentos e métricas; não operar servidor redundante enquanto SQLite versionado atender às necessidades |
| PyWhy DoWhy | **Candidato P2** | Inferência causal sob hipóteses identificáveis; não extrapolar de correlações |
| Microsoft GraphRAG | **Referência somente** | Mantido, porém com novas funcionalidades não prioritárias no upstream; não fazer dependência central |
| Hermes self_improvement | **Reutilizar contrato** | PROMOTED somente com testes, benchmark, auditoria independente, registro versionado e rollback |

Links e contratos canônicos estão em `config/ivo_ferramentas_github.v1.json`. Licença permissiva do código não garante uso livre de dados, marca, API ou pesos de modelos. Não foi copiado código desses projetos.

## Próxima execução E2E necessária

1. **Conhecimento**: unir Research AI e Knowledge Factory/Segundo Cérebro com claims citados, direitos, temporalidade, contradição e supersession; manter fatos e conhecimento técnico versionados.
2. **Backfill**: ingestão real de fontes oficiais aprovadas, histórico mais longo tecnicamente acessível, snapshots imutáveis, controle de correções e cadastro de séries confiáveis.
3. **Preditivo**: experimentar StatsForecast e MLForecast por produto/região/horizonte; manter baseline seasonal-naive. River só deve aprender de novas observações liberadas e rótulos efetivamente publicados.
4. **Cross-domain**: associar produção/clima/mercado/portos/frete a corredores e cadeias com universo temporal e unidades consistentes, sem supor causalidade.
5. **Autoaprendizado**: proposta de alteração -> sandbox -> testes -> benchmark out-of-sample -> auditoria -> promoção pela autoridade externa -> observação de resultados -> rollback.
6. **Conversação, voz e alertas**: API/SDK autorizado, interfaces read-only inicialmente; alertas apenas para evidência operacional homologada; WhatsApp AI pode entregar mensagens, mas o IVO/NIVON é autor dos conteúdos.
7. **Operação**: teste E2E na nuvem, backups/restauração, quotas gratuitas verificadas, monitoramento e segurança. Sem deploy até homologação.

## Gates estritos

- Dado candidato não recebe condição OBSERVADO por conveniência, nem notícia equivale valor medido.
- Programação portuária não é navio embarcado; anúncio de frete não é frete realizado.
- Culturas agrícolas usam calendário de safra; meteorologia/hidrologia preservam seus instantes e observações.
- Treino e features não podem usar informações ainda não publicadas no instante da previsão.
- Cenários de política e geopolítica devem distinguir fato confirmado, hipótese e impacto calibrado.
- Na ausência de fonte suficiente, responder "não identificável / dados indisponíveis" em vez de inventar estimativa.
- Nenhum agente pode modificar direitos, custos, código, fonte canônica ou versão ativa de modelo autonomamente.
- Infraestrutura futura permanece em cloud sem depender do notebook, com teto de custo zero e sem serviços pagos não autorizados.
