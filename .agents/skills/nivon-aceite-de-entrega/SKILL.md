---
name: nivon-aceite-de-entrega
description: Conferir se uma tarefa GitHub foi realmente implementada, integrada e comprovada antes de declarar sucesso.
---
# Aceite técnico NIVON
1. Identifique PR, commit base/head, dependências e código já existente. Evite abrir PR concorrente que repita solução de outra frente.
2. Rode teste de integração/end-to-end relevante. Unit test verde sozinho não comprova publicação.
3. Exija evidência de execução no ambiente certo e dados reais, sem expor credenciais. Em PR, deploy pulado é **PULADO**, não sucesso de go-live.
4. Use `nivon.integracoes_ia.engenharia.aceite_trabalho` apenas para organizar evidências PENDENTES. O aceite oficial do M1 fica no mecanismo canônico já previsto.
5. Não faça merge, deploy faturável ou libere recurso público sem autorização exigida pelo projeto. Registre bloqueios e próxima ação objetiva.
