# NIVON — engenharia contínua, qualidade e autonomia de tokens

Data de avaliação: 23/10/2026. Inventário de oportunidades, não declaração de instalação. O `doctor` detecta apenas comandos presentes no host; a CI do GitHub valida o código Python, não comprova ferramentas instaladas no computador.

## Operação diurna x noturna

- Dia: pesquisar, programar, testar, executar `doctor`, `plan`, `night-status`, `python -m nivon.qualidade`, analisar CI e preparar PRs.
- Noite: execução autônoma **somente de 20:00 até 06:00 no fuso America/Cuiaba**, com margem de 15 minutos para testes e integração, além do timeout da tarefa.
- O script `scripts/nivon-autonomo.sh`, a skill `/nivon-autonomo` e o supervisor verificam horário **antes de movimentar fila ou iniciar agentes**. `status` e `stop` funcionam a qualquer hora.
- O horário noturno **não agenda nada**: PC/servidor precisa estar ligado e o operador precisa iniciar o processo; não usar GitHub Actions como substituto para CLIs autenticadas.

## Ferramentas para código melhor e menos tokens

| Ferramenta | Uso no NIVON | Situação e custo adicional |
| --- | --- | --- |
| [Ruff](https://github.com/astral-sh/ruff) | Lint rápido, feedback determinístico; produzir tarefas a partir de violações | integração opcional existente; nenhuma instalação forçada |
| [ty](https://github.com/astral-sh/ty) | Tipagem incremental de Python, prevenção de defeitos | detectável no doctor; beta, não é gate obrigatório |
| [ast-grep](https://github.com/ast-grep/ast-grep) | Busca/revisão estrutural de código multilinguagem | detectável; não habilitado nos agentes |
| [Aider](https://github.com/Aider-AI/aider) | Mapa de repositório com orçamento explícito de tokens | aproveitar técnica; índice AST nativo já existe |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | Testes generativos e investigação de invariantes em parsers/coletoras | recomendado para pilotos, demanda dependência e benchmark |
| [pytest-xdist](https://github.com/pytest-dev/pytest-xdist) | Reduzir tempo de testes (não tokens por si só) | opcional após medir custo CPU e isolamento |
| [Semgrep](https://github.com/semgrep/semgrep) | Regras de análise estática e detecção de erros e padrões inseguros | detectável; revisar licença e escopo comunitário |
| [Gitleaks](https://github.com/gitleaks/gitleaks) | Encontrar segredos antes de versionar | detectável, invocação automatizada requer validação local |
| [OSV-Scanner](https://github.com/google/osv-scanner) | Vulnerabilidades em dependências | detectável; consulta ao serviço pode exigir rede, nunca automática |
| [Ollama](https://github.com/ollama/ollama) | Modelos locais como capacidade *adicional* independente das cotas Claude/Codex | somente detecção: testar RAM/VRAM, licença/modelo e qualidade antes de conectar |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Inferência local, hardware otimizado, sem franquia comercial de tokens por chamada | avaliação futura; não integrar sem hardware confirmado |

**Decisão:** priorizar primeiro recursos nativos, verificadores determinísticos e índices locais. Ferramentas adicionais só após medir erro, retrabalho, tempo e tokens. Não instalar Serena e Codebase Memory juntos, nem múltiplos proxies MCP. Cache de prompts não aumenta automaticamente os limites dos planos Claude e Codex.

## O que já foi incorporado na branch

1. `nivon.janela_noturna`: valida fuso, janela e margem para testes; nega execução diurna.
2. `nivon.qualidade`: análise AST offline de `src/` e `tests/`, sem executar os arquivos, mais Ruff opcional selecionando regras críticas `E9,F821,F822,F823`.
3. `nivon.ferramentas doctor`: informa disponibilidade de ferramentas, sem instalar nem configurar credenciais.
4. `nivon.contexto_codigo`: indexação Python por hash e dicas de símbolos limitadas; não injeta arquivos inteiros no prompt.
7. Claude Code é invocado com `--restricted --safe-mode --no-session-persistence`, sem plugins/hook/MCP de usuário, e somente ferramentas de arquivo explicitadas; `AGENTS.md` deve ser lido diretamente pela tarefa. Isso reduz carregamento de contexto, mas ainda exige teste no host para validar a versão da CLI.
5. `nivon.planejador`: tarefas priorizadas com dependências, gates de licença/risco e ítems de qualidade Ruff; não toma texto de issue como instrução livre.
6. `nivon.autonomia`: duas worktrees em paralelo e integração serializada na branch local `autonomo/integracao`, com regressão offline em contêiner sem rede.

## Como avaliar, sem ativar agentes

```bash
bash scripts/nivon-autonomo.sh night-status
bash scripts/nivon-autonomo.sh doctor
bash scripts/nivon-autonomo.sh plan
PYTHONPATH=src python -m nivon.qualidade --json
```

Quando, **à noite** e após validação no host, o operador poderá usar `bash scripts/nivon-autonomo.sh` ou `/nivon-autonomo`. Não há scheduler ativo e não foram iniciadas CLIs autenticadas nesta etapa.

## Aumentar capacidade sem prometer tokens infinitos

- Acesso oficial a modelos maiores ou cotas maiores depende de plano/provedor, custos e autorização.
- Modelos locais via Ollama ou llama.cpp podem processar requisições fora das cotas Claude/Codex. Isso **não** aumenta as cotas oficiais. Hardware, consumo de energia, espaço, licença do modelo, contexto e confiabilidade limitam a produção.
- Provedores com planos gratuitos têm limites próprios e regras de uso; nenhum roteamento deve criar contas em massa ou contornar quotas.
- Um eventual terceiro executor local deve receber tarefas de risco baixo, isoladas, com os mesmos gates e testes de qualidade. Somente após benchmark comparar conclusões por token, falhas e regressões.

## Evidências e próximo gate

Código/testes de CI desta PR, sem comprovação de economia de tokens no PC. Próximo gate: verificar flags de versão do Claude/Codex, medidas de hardware, isolamento real, escolha de único mecanismo local de inferência e teste ponta a ponta noturno com orçamento autorizado.

### Gate de autenticação no piloto

`--bare` do Claude Code não suporta recuperar OAuth/keychain da assinatura. O NIVON utiliza `--safe-mode`, que reduz plugins, hooks, skills e MCPs e preserva login oficial. O `doctor` detecta as flags e métodos de autenticação **sem chamar modelos**; execução com credenciais de API faturada/terceiros é bloqueada. Fonte: [Claude CLI](https://code.claude.com/docs/en/cli-reference).
