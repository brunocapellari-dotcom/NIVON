---
name: nivon-autonomo
description: Inicia a produção autônoma e cooperativa do NIVON com Claude Code e Codex, sem ativar nuvem ou custos novos.
disable-model-invocation: true
argument-hint: "[minutos] [numero-de-tarefas]"
---

# NIVON — produção autônoma

Quando invocada pelo usuário com `/nivon-autonomo`, esta skill deve executar **uma única vez** a sequência abaixo, sem construir ciclos próprios em mensagens da IA.

1. Ler `AGENTS.md` e `docs/COOPERACAO_CLAUDE_CODE_CODEX.md`. **Antes de qualquer escrita**, executar `PYTHONPATH=src python -m nivon.janela_noturna check` e `PYTHONPATH=src python -m nivon.ferramentas doctor`. Fora da janela de 20h às 6h (America/Cuiaba), não iniciar supervisor nem alterar backlog; permitir apenas `plan`, `doctor` e pesquisa.
2. Executar planejamento determinístico (código, dependências e GitHub somente leitura):
   `PYTHONPATH=src python -m nivon.planejador refresh --github`
   As issues só entram na fila com label `nivon-auto-ready` e bloco estruturado `NIVON-AUTO`. Na ausência do gh CLI, usar roteiro local.
3. Chamar `PYTHONPATH=src python -m nivon.autonomia start --minutes 120 --max-tasks 8 --per-task 15` para iniciar o supervisor **local**.
4. Responder com instruções curtas:
   `PYTHONPATH=src python -m nivon.autonomia status` e
   `PYTHONPATH=src python -m nivon.autonomia stop`.
5. Parar. Não abrir loops de mensagens, não usar bypass de permissões, não instalar pacotes nem ativar serviços externos.

Caso o usuário solicite outros limites, aceitar somente 1–480 minutos, 1–30 tarefas e 2–60 minutos por tarefa. Se a CLI não autorizar o comando local, não alterar configurações de segurança para contorná-la. O operador pode adicionar permissão restrita para esse comando após revisar sua implementação.

Regras: **execução autônoma apenas à noite no fuso America/Cuiaba**, sem agendamento automático. Claude e Codex são ambos programadores, em worktrees separados; cada tarefa é testada; merges e deploys são proibidos; somente branch local. Um supervisor externo precisa permanecer em host ligado e autenticado; esta skill não transforma a conversa em execução permanente.
