# IVO — fronteira Hermes de autenticação/autorização (20/10/2026)

**Status: CODE_ONLY, OFFLINE, integração contratual; NÃO autenticado end-to-end contra infraestrutura real.** PR #24 permanece draft e empilhada sobre PR #7; PR #13 coordena integração das 14 frentes. Nenhum serviço, banco, credencial, coletor, deploy ou pagamento ativado.

## Auditoria objetiva

- Hermes já contém ServiceIdentity / IdentityVerifier / GoogleOIDCVerifier em `src/hermes/auth.py`.
- Hermes já contém PolicyRequest / PolicyDecision em `src/hermes/domain.py`, CompositePolicyEngine em `authorization.py` (OPA e OpenFGA opcionais), e middleware de controles em `control_auth.py`.
- O middleware de controle Hermes usa `authenticated_actor("local-owner")` para algumas operações: isso **não é** evidência de que todo endpoint leia identity estrita em produção. **IVO não herda fallback de owner.**
- PR #24 já tinha recuperação read-only com callback, mas não prova origem criptográfica nem identidade de tenant.
- PR #7 avançou durante esta rodada; branch base da PR #24 não inclui automaticamente alterações posteriores (como a ponte IBGE/PAM). A reconciliação fica com a integração para evitar sobrescrever trabalho em paralelo.

## Contrato entregue

`src/nivon/ivo_hermes_gateway.py` compõe, sem reescrever autenticação ou OPA:
1. Recebe token **apenas** do transporte servidor autorizado; invoca `IdentityVerifier.verify(token)`. Exige subject, issuer e audience específicos.
2. Consulta `scope_lookup(subject)`, resolvido exclusivamente no servidor (sem `tenant`, `ator` ou `projeto` vindos da pergunta ou de claims).
3. Consulta o `resource_lookup(claim)` server-side para comprovar, dentro do contrato recebido, tenant/projeto, claim ID, fonte, SHA do documento, SHA do texto e auditoria. Nega qualquer divergence, direito ausente ou ACL futura para corte retrospectivo.
4. Prepara `PolicyRequest` com `actor=subject`, `action=evidence:read`, `resource=nivon:evidence:{tenant}:{document_sha256}:{claim_id}`, `relation=can_read`, `risk=low`, `trust=untrusted`, sem permissão de escrita/admin/gasto.
5. Exige `CompositePolicyEngine.external_required=True`, `opa` e `openfga` presentes e decisão literal `allowed is True` e `requires_approval is False`. Falhas ou respostas ambíguas bloqueiam sem expor texto.
6. Só então chama os módulos existentes `montar_pacote_evidencias`, `recuperar_claims_asof`, `ivo_planejador`; sem LLM, rede, alteração canônica, treino ou execução preditiva.

A checagem de atributos `opa/openfga` configura um **gate contra política local**, não é prova de que ambos estão disponíveis, corretos ou que o verificador de identidade foi instalado pelo servidor. A autoridade real depende de injeção de componentes confiáveis e de ensaio E2E.

## Wiring exigido, ainda NÃO implantado

- Em bootstrap autenticado Hermes, importar `hermes.auth.GoogleOIDCVerifier`, `hermes.domain.PolicyRequest` e `hermes.authorization.build_policy_engine`.
- Fornecer issuer/audience de servidor e `scope_lookup` respaldado por diretório de membros do tenant; não mapear subject para `owner` por padrão.
- Providenciar um registry independente de evidências com SHA do conteúdo e proveniência/verificação de direito por operação; nunca confiar nos metadados fornecidos pelo cliente.
- Configurar `build_policy_engine(allow_external_actions=False, opa_url=..., openfga_url=..., openfga_store_id=..., external_required=True)` com comunicação HTTPS, identidade serviço-a-serviço, timeout, trilha de auditoria e sem fallback em falhas.
- Injetar `policy_request_factory=hermes.domain.PolicyRequest`; não construir outro cliente OPA ou verificador de JWT dentro do IVO.
- Definir rotas autorizadas read-only e testes de tenant/recurso reais. A rota não está presente no NIVON, portanto não há endpoint exposto inadvertidamente.

## Testes

`tests/test_ivo_hermes_gateway.py` usa doubles inteiramente sintéticos de IdentityVerifier, Scope/Resource Lookup e Policy Engine. Verifica bloqueio sem token, issuer/audience incorretos, escopo forjado, acesso entre tenants, hash/assinatura de texto divergentes, ACL futura, indisponibilidade OPA/registry, aprovação pendente, corte futuro, prompt injection, operações apenas leitura e precedência das verificações antes do planejamento.

**Limites:** doubles não provam assinatura OIDC, OPA/Rego, modelo OpenFGA, direitos reais, isolamento no transporte, logs seguros nem conectividade. Sem testes E2E autenticados reais, modelo não é homologado.

## Backlog ordenado

1. **P0 — E2E real autenticado**: serviço Hermes + tenant directory + registry de evidências + OPA/OpenFGA em sandbox isolado; tests allow/deny/cross-tenant e auditoria; dependente de infraestrutura e políticas homologadas.
2. **P0 — Prova de proveniência de claims**: provas externamente verificadas, snapshots Second Brain/Knowledge Factory, versões, supersession e direitos por operação; sem cópia de memória.
3. **P0 — Rebase/reconciliação PR #7/#24/#13**: preservar novas pontes PAM e testes de ambas branches; CI completa no novo HEAD sem deploy.
4. **P1 — Avaliação RAG**: gold set adversarial, temporalidade as-of, autorização, recall/citação, abstenção; sem ativar LLM antes de critérios de aceite.
5. **P1 — Integração motores homologados**: metadados obrigatórios de fonte, horizonte, unidade, incerteza e backtesting walk-forward real autorizado.

**Decisão de operação:** manter draft; CI sintética aprova contrato de software apenas, não acesso a produção.
