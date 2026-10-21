# NIVON — Ciclo 05: convergência IVO AI com motor central e Maritime

**Data da rodada:** 21/10/2026. **Estado:** candidato em draft, sem merge/deploy/autorização de operação.

## Proveniência e escopo integrado

- **Base congelada:** PR #41, commit `9a12ea81a406b46c0901eeb948d7a9d945483ca4`.
- **Origem IVO:** PR #7, commit `0c45d466a17136d878d105c2deb41308d30466a3`, delta contra a base `662dbd5cdb685346ceba20d49953e8bf2508cb0e`.
- **57 arquivos novos** da PR #7 foram adicionados por SHA original, preservando implementações e testes das outras frentes.
- **1 contrato compartilhado:** `pyproject.toml`, reconciliado sem perda de `agro`, `forecast`, `ports`, `excel`, `analytics`, `agents` e `auth`. Extras de IVO ficam opcionais: `ivo-ml` (pandas, scikit-learn, mlforecast), `ivo-online` (river), `ivo-query` (duckdb). Dependências normais do NIVON permanecem vazias; nenhuma instalação extra automática.

## Arquitetura e separação de responsabilidades

- `ivo_planejador.py` faz planejamento lexical e leitura de contratos já versionados, sem executar motores, rede ou LLM. Roteamento para SOJA, METEOROLOGIA, FRETE_RODOVIARIO e MARITIMO retorna `PLANO_OFFLINE_SEM_DADOS_HOMOLOGADOS`, `ferramentas_executadas=0`, `previsao_validada=false`, `resposta_numerica_autorizada=false`.
- `ivo_conhecimento_adapter.py` recebe claims **de snapshot declarado curado** com SHA, natureza da evidência e datas as-of; `aprovacao_externa_verificada=false` por padrão. O IVO **não escreve no Segundo Cérebro**, não se atribui a função de Knowledge Factory e trata conteúdo como dado não confiável.
- Observação real ≠ estimativa ≠ projeção ≠ informação de line-up; nenhuma resposta gerada pelo IVO pode alterar `publication_allowed=false` do gateway Maritime, nem gerar frete municipal agregado, porto/escala realizada, tonelagem ou posição AIS não comprovada.
- `ivo_previsao_ledger.py` e os laboratórios registram/avaliam evidências locais; não autorizam treinamento produtivo nem promoção de modelos. BACKTEST e modo LIVE declarados pelo item não substituem homologação operacional.
- `ivo_elegibilidade_rotulos.py` exige origem, temporalidade, direito de treinamento e prova independente. Não usar rótulos SINTÉTICOS em previsão pública ou misturar vintages.

## Correção de segurança nesta integração

O adaptador original aceitava `fonte_url.startswith("https://")`, o que não validava origem. A integração reforçou a análise com `urlsplit` e bloqueios de IP literal, `localhost`, domínios locais, credenciais de URL, porta divergente, fragmentos, URLs sem domínio público e caracteres de controle. Isso protege a **aceitação do link de proveniência**; continua necessária política de egress/DNS/SSRF na ferramenta que, no futuro, for efetivamente abrir URLs.

## Testes registrados

- [GitHub Actions 39603950020](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39603950020): após incorporar 57 arquivos e reconciliar `pyproject`, **1.962 testes, 0 falhas, 3 ignorados**.
- [GitHub Actions 39604298409](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604298409): após reforço URL e regressões adversariais, **1.966 testes, 0 falhas, 3 ignorados**.
- Novos testes de integração `tests/test_integracao_ivo_multidominio.py` comprovam planejamento cross-domain sem execução, distinção de conhecimento projetado e estado Maritime com dados desconhecidos, e instalação opcional das bibliotecas.
- `tests/test_ivo_conhecimento_adapter.py` acrescenta rejeição de URLs com credenciais, IP/host privado, portas indevidas, fragmentos e URL não-HTTPS.
- **Essas evidências são de teste local/sintético em CI**. Os três testes ignorados não devem ser tratados como capacidade validada; verificar motivo antes de liberar extras científicos.

## Pendências e sequência recomendada

1. Homologar contrato canônico IVO ↔ Knowledge Factory/Context Fabric/Hermes: autenticação da origem de `auditoria_id`, validade das provas, revogação temporal, não duplicar memória e garantir isolamento entre projetos.
2. Auditar R06 (prompt injection de documentos e URLs, SSRF/HTML/PDF/ZIP/XLSX hostis, egress de ferramentas executoras).
3. Executar integração e testes de versão real dos extras IVO em ambiente isolado, sem custo não autorizado; avaliar reprodutibilidade, segurança e licenças.
4. Desenvolver política determinística de uso de evidência conforme `as-of`, cobertura/fonte, proibição de médias de frete municipal e vedação de previsão não homologada; simular casos adversariais com licença de teste.
5. Resolver a duplicidade `outbox_briefing.py` / `outbox_whatsapp.py`, riscos NPM do cockpit e fontes reais dos cinco portos antes de release conjunto.
6. Homologar R01/R03 com dados reais autorizados, R04/R05 de métricas/predições, backup-restauração, observabilidade, custos e governança para produção.

**Sem promoção:** todos os releases, envios WhatsApp, coletores, treinos e atualizações de memória canônica permanecem bloqueados. `main` não deve ser alterada sem revisão independente.
