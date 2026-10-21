# NIVON — Auditoria independente do workflow de acessos privados

**Data:** 21/10/2026, horário de Mato Grosso.  
**Implementação auditada:** PR #61 `integration/nivon-acessos-core-convergencia-20261021`, SHA congelado `95b323644e62b56decd5e878a741abe3d1d04167`.  
**Auditoria independente:** PR #72, branch `audit/acessos-runner-context-20261021`.  
**Escopo:** compatibilidade estrutural GitHub Actions do workflow manual de credenciais USDA, ANA e INMET. Sem solicitar nem acessar segredos.

## Evidências verificáveis

1. [Execução da integração 39660585590](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39660585590) — conclusão `failure` com **zero jobs** retornados pela API GitHub Actions. Outras execuções da mesma família, incluindo 39661694657, mostram falha de inicialização equivalente. **Sem job não há log de runner**, e portanto não atribuir o erro formal do serviço sem annotation correspondente.
2. `.github/workflows/acessos-privados.yml` no SHA da PR #61 tem `NIVON_INMET_DIRETORIO_PRIVADO: ${{ runner.temp }}/nivon-bdmep` em `jobs.validar-inmet.env` (escopo de job). O contexto `runner.*` é permitido em **`steps.env`** e etapas executáveis, mas não em `jobs.<job_id>.env`; a expressão nesse escopo é um defeito de validação de workflow.
3. No mesmo SHA, os passos de **criar diretório** e **executar o smoke INMET** herdam essa variável do job; não recebem independentemente a variável de ambiente com contexto válido. A correção requer declarar o mesmo path em ambos os passos.
4. `tests/test_auditoria_workflow_acessos_privados.py` contém dois testes adversariais para detectar o escopo errado e dois controles de acionamento manual e ambiente restrito. Um controle relativo à suíte de CI offline usa skip explícito quando o workflow ainda não foi introduzido nesse SHA, em vez de atribuir falha da estrutura a arquivo que só existe em `main`.
5. A `main` atual, SHA `ca9d19585e8eb807cdac5b2a1cbe48678b4ef479`, contém **versão diferente** do mesmo workflow que já moveu a referência ao contexto para o ambiente **dos passos**. Isso é evidência de correção de design disponível; não prova que a branch PR #61 a tenha incorporado ou que uma execução manual live tenha sido bem-sucedida.
6. A `main` segue com `protected=false` na leitura da API de branch. Nenhuma conclusão de segurança definitiva deve ser tirada somente de execução de testes sintéticos.

## Não conformidades / tratamento

| ID | Prioridade | Motivo | Aceite |
|---|---|---|---|
| NC-AUD-022 | P0 para a integração de acessos | Contexto `runner.temp` no `jobs.env`, escopo inválido; workflow privado falha antes de criar jobs nas execuções observadas | Remover `runner.*` de `jobs.env`; workflow válido, agendando job em execução manual **na main** com Environment protegido e aprovação adequada |
| NC-AUD-023 | P1 | Mesmo diretório privado INMET não está configurado explicitamente em ambos os steps quando removido o `jobs.env` inválido | Prover path por `steps.env` no step que cria diretório e no step de leitura ZIP, sem imprimir, salvar artifact, subir arquivos ou expor o URL |

## Padrões mínimos de aprovação posterior

- Teste sintético `unittest` para todos os caminhos, sem secrets ou chamadas reais nas PRs.
- Workflow manual `workflow_dispatch` exclusivo de `main`, `mode=preflight` como padrão, `live` opt-in, GitHub Environment `nivon-fontes-privadas` com revisão e secrets protegidos.
- Não editar nem consultar credenciais no GitHub, Gmail ou terminal da auditoria; não anexar dumps de exceções que possam revelar tokens ou URLs.
- A execução `live` é uma etapa operacional separada e exige comprovar aprovações de ambiente, disponibilidade de credenciais e direitos/licenças. Não confundir `unittest` verde, preflight de formato e autenticação real USDA/ANA/INMET.
- As falhas jobless são evidência de workflow rejeitado, não necessariamente confirmação de indisponibilidade de USDA, ANA ou INMET.

**Parecer:** manter a PR #61 em rascunho até validar o arquivo YAML corrigido e obter CI consistente. O teste de auditoria não alterou lógica de produção nem utilizou credenciais.
