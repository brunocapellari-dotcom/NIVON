# IVO — proveniência canônica Second Brain / Research AI (21/10/2026)

**Situação: código read-only e testes sintéticos, NÃO homologado com dados reais.**
A branch da PR #24 continua empilhada sobre PR #7, e PR #13 mantém coordenação de integração. Sem merge, deploy, coletas, serviços pagos, importação de dados reais ou promoção de conhecimento.

## Contratos existentes, inspecionados em 21/10/2026

- **Research AI**, `app/models/contracts.py`: ResearchPackage registra `claims`, `evidence`, `sources`, `generated_at` e `audit_passed`. Pesquisa, mesmo entregue/auditada, **NÃO** equivale à promoção canônica. `app/integrations/knowledge_factory.py` apenas submete pacote a `POST /v1/source-packages`; não escreve conhecimento.
- **Second Brain**, `second_brain/agrolog_release.py`: `AgroLogKnowledgeRecord` requer status `CANONICO` + `KnowledgeFactoryPromotion(promoted_by=knowledge_factory, audited, validated, decision_id)`, `evidence_id`, `content_hash`, `source_id`, `dates`, `valid_from/valid_to`, classificação, `supersedes/contradicts/derived_from`. **Esse modelo valida declarações, mas não autentica o emissor da decisão nem fornece aprovação datada por si só.**
- **Second Brain**, `second_brain/store.py`: store de Markdown governado com conflito de IDs; IVO não escreve nele, não varre o vault sem escopo e não cria memória duplicada.
- **NIVON**, `ivo_conhecimento_adapter.py`, `ivo_pacote_evidencias.py` e `ivo_hermes_gateway.py`: mecanismos existentes de corte temporal, seleção de claims e ACL externa, mantidos sem duplicação.

## Implementação de contrato de proveniência

`src/nivon/ivo_second_brain_bridge.py` aceita um lote limitado de snapshots estruturados (`AgroLogKnowledgeRecord.model_dump(mode='json')`) com bytes de evidência. É função pura: nenhuma rede, busca de arquivos, escrita ou LLM.

Um registro só entra na saída como `ClaimCurado` **candidato à consulta** se:

1. Status exatamente CANONICO, `promotion` Knowledge Factory auditada e validada; nenhuma classificação de ResearchPackage/Research AI é promovida.
2. Verificação de integridade com SHA-256 completo do conteúdo da evidência e SHA-256 canônico do registro (ordem de chaves determinística). Recusa hash fraco/alteração, ID ambíguo, fonte trocada ou exportação excessiva.
3. Instantes `publication_date <= collection_date <= exportado_em <= corte`; `valid_from <= corte < valid_to` quando houver término. Atestação de autoridade possui `collection_date <= aprovado_em <= verificado_em <= corte`.
4. Callback confiável **fornecido pelo servidor** atesta coincidência de claim, evidence, fonte, hash do registro, hash da evidência, decisão, tenant, projeto consumidor, direito de consultar e vigência as-of. Ausência/falha/bool ambíguo causa rejeição do **lote inteiro**.
5. Preservação de `source_id`, URL primária HTTPS informada pelo registro confiável, competência e referência com granularidade **DIA** (00 UTC somente convenção de transporte), classificação da origem e relações `supersedes`, `contradicts`, `derived_from`, **sem inferência causal**.

A saída não expõe aprovação real, não dá direito de redistribuir nem treinar, não é resposta do usuário. Os `ClaimCurado` resultantes ainda devem atravessar `GatewayHermesIVO`, cuja autenticação criptográfica/OPA/OpenFGA precisa ser configurada e homologada separadamente.

**Segurança:** callback não é assinatura/PKI; um verificador falso sempre pode fabricar uma atestação. O status declarado dentro do registro não é prova independente. O backend autorizado deverá verificar decisões e políticas de direitos em armazenamento seguro e auditar cada invocação. As ACLs do Hermes NÃO são construídas automaticamente a partir dos metadados do Second Brain.

## Uso offline experimental

```python
from nivon.ivo_second_brain_bridge import (
    ExportacaoSegundoCerebro, normalizar_exportacoes_canonicas
)

# O backend fornece exports datados e bytes auditados, além de verificador
# REAL e server-side; nenhuma atestacao criada pela LLM é confiável.
resultado = normalizar_exportacoes_canonicas(
    exportacoes=exports, corte=corte_utc, tenant=tenant_autenticado,
    verificador=servico_de_atestacao_confiavel,
)
# Entregar resultado["claims"] ao gateway Hermes autorizado, nao ao usuario.
```

## Testes e limites

`tests/test_ivo_second_brain_bridge.py` contém casos sintéticos de promoção indevida, auditoria falsa, hashes, tenant/projeto, direitos, cronologia, exportação posterior ao corte, supersession, fonte, atomicidade do lote, classificações, relações e fluxo integral offline normalização → gateway Hermes → evidência citável.

Dados sintéticos não provam certificação, segurança de um servidor real, contexto completo ou acesso autorizado a arquivos canônicos. Os testes em GitHub Actions no SHA final são a evidência de software.

## Backlog executável

1. **P0 — Assinatura e prova externa**: definir transporte de exportação autorizado e atestação verificável vinculada a decision_id, tenant, operação, source snapshot e instante; autenticar origem no Hermes.
2. **P0 — Snapshot histórico completo**: ledger de versões, exportações na época do corte, estado de supersession no corte, hash imutável e capacidade de replay sem look-ahead.
3. **P0 — Reconciliação**: preservar PR #7 (inclusive IBGE/PAM) e PR #24 ao integrar com PR #13; executar suíte integral sobre HEAD reconciliado.
4. **P1 — E2E com serviços reais**: Hermes IdentityVerifier/OIDC, OPA/OpenFGA e Knowledge Factory/Second Brain, dados licenciados e validação de proteção entre tenants.
5. **P1 — Qualidade RAG e resposta IVO**: gold sets temporais/adversariais, citações, abstinência, incerteza, acesso a motores verificados com aprovação humana.

Nenhuma homologação ou deploy está autorizada por este documento.
