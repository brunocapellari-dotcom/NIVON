# Política de segurança — NIVON

O NIVON é um projeto de uso privado, embora o repositório de código esteja **público**. Não considere públicos os dados de fornecedores, credenciais, séries restritas ou os ambientes de execução.

## Reportar vulnerabilidade
Não publique credenciais, tokens, endpoints privados nem exemplos com dados sensíveis em issues, pull requests ou anexos públicos. Use o canal **Security → Advisories → Report a vulnerability** se o proprietário habilitar o relato privado. Se ele não aparecer, procure o proprietário por um canal privado já conhecido; não abra issue pública com a evidência.

## Escopo de proteção
- Terminal Cloud Run autenticado; nenhuma autorização anônima de invocação.
- Contas de serviço separadas para deploy, coleta e consulta.
- OIDC/WIF no lugar de chaves JSON de conta de serviço no GitHub.
- Menor privilégio no IAM; configurações de produção protegidas por ambiente.
- GitHub Actions sem credenciais nos testes de pull request e ações fixadas em commits SHA.
- Fontes privadas e séries sujeitas a restrições contratuais nunca são anexadas a artefatos públicos do GitHub Actions.
- Nenhuma alteração de IAM, deleção de segredos ou dados, migração de infraestrutura ou custo novo sem autorização explícita.

## Conduta após incidente
1. Interromper a credencial comprometida e rotacioná-la no fornecedor.
2. Investigar usos e logs; preservar evidências sem republicar o segredo.
3. Corrigir código, permissões, pipelines e histórico exposto quando necessário.
4. Documentar impacto, mitigação e validação antes de reabrir o acesso.

Versão de referência: 26/10/2026. Ver `docs/SEGURANCA.md` para a implantação operacional.