# IVO — aprendizado contínuo e predição verificável

Status: contrato inicial e testes offline. **Não há treinamento autônomo, LLM em produção, coleta recorrente nem deploy.**

## Responsabilidades

IVO é a interface/orquestrador cognitivo agro do NIVON. Não replica os coletores, motores ou dados; usa contratos NIVON de fontes, vintages, indicadores, balanços, relatórios e auditoria. Hermes é uma referência de governança, não dependência obrigatória. Research AI executa pesquisa autorizada; Knowledge Factory/Segundo Cérebro detém o conhecimento canônico. Toda atualização canônica deve passar por auditoria independente.

## Ciclo de conhecimento

Lacuna identificada -> busca de fontes autorizadas (papers, livros, órgãos, GitHub) -> aquisição lícita -> hash, licença e quatro datas -> extração de claims -> comparação entre organizações independentes -> detecção de contradição -> candidato segregado -> auditoria independente -> publicação canônica externa -> retrieval com citações -> avaliação de respostas -> novas lacunas.

Documentos, páginas e resultados de ferramentas são **dados não confiáveis**, nunca instruções do sistema. A versão de cada claim, sua referência e vigência devem permanecer recuperáveis. Aprender fatos novos via RAG/memória não equivale a retreinar os pesos do LLM.

## Ciclo de machine learning

Dados reais versionados e autorizados -> features calculadas exclusivamente com informações disponíveis no instante da previsão (*as-of*) -> baseline sazonal/ingênuo -> candidatos estatísticos/ML -> backtesting walk-forward e séries congeladas -> avaliação por cultura/corredor/horizonte -> estimativa de erro e intervalos calibrados -> auditoria independente -> promoção governada fora do IVO -> monitoramento de drift/erro -> rollback ou novo ciclo.

Para clima, produção, preços, fretes, comércio exterior, consumo industrial, hidrologia e portos, usar modelos específicos. Não supor que uma técnica supere todas; combinar métodos somente após validação. Não declarar causalidade a partir de correlações ou identidades contábeis. Para previsões, explicar intervalo, cenário, principais drivers, horizonte e data de corte. Não inventar precisão nem autoajustar dados observados.

## Contratos implementados nesta mudança

- `src/nivon/ivo_aprendizado.py`: elegibilidade de claims com duas organizações distintas, fonte primária, SHA-256, direito aprovado, ordem de publicação/coleta e corte. Contradições ficam em quarentena.
- Mesmo módulo: backtest de previsões mensais pontuais com pelo menos seis folds, datas verificadas, MAE, WAPE e comparação com baseline. Melhorias ficam como candidato para auditoria; resultado sintético **não** homologa.
- `tests/test_ivo_aprendizado.py`: casos positivos, negativos, de licenças e vazamento temporal.
- Nenhuma função do módulo promove conhecimento ou modelo, reescreve código, publica previsões, chama rede ou ativa custos.

## Integração completa a realizar (não reivindicar como pronto)

1. Roteador IVO para ferramentas read-only e consultoria dos motores do NIVON, com rastreabilidade por fonte, data, unidade e versão.
2. Integração de pesquisa, grafo de afirmações e Knowledge Factory/Segundo Cérebro por contrato API, com controle de escopo. Não criar um segundo cérebro concorrente.
3. Feature store e registro de predições imutáveis, com quatro datas e histórico retrospectivo permitido; sem usar revisões futuras nos folds.
4. Treinamento periódico ou por drift, com recursos gratuitos apenas se houver limite, quotas e persistência/recuperação comprovados na nuvem; notebook é só terminal.
5. Avaliação por setor, horizonte e regime (seca, excesso de chuva, choque de combustível, etc.), incluindo MAE, WAPE, cobertura dos intervalos e desvio versus baseline.
6. Registro e aprovação de propostas integrado ao mecanismo Hermes `self_improvement` por contrato — PROPOSED -> SANDBOX -> TESTS -> BENCHMARK -> A/B -> AUDIT -> PROMOTED/REJECTED/ROLLED_BACK. Agentes nunca autopromovem suas próprias capacidades.
7. Auditor de qualidade, direitos de fonte, segurança, explicabilidade, deriva, rollback, orçamento e riscos operacionais. Alterações de código/deploy/despesa permanecem bloqueadas sem autoridade pertinente.
8. Pipeline E2E verificável em cloud, com evidências de execução, backup/restore, idempotência e relatório de performance; sem go-live antes de homologação.

## Limites conhecidos

`avaliar_conhecimento` valida contratos declarados, mas não comprova a autenticidade, veracidade ou independência das organizações. `avaliar_modelo` valida folds apresentados, mas não comprova que treino, features e fontes tenham sido preparados corretamente fora da amostra. Ambos são **filtros iniciais**, não certificadores de aprendizado autônomo. Aprimoramento deverá ser medido contra resultados posteriores e pode falhar; nenhum modelo promete prever o futuro com certeza.
