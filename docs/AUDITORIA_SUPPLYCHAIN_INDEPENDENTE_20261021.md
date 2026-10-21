# NIVON — Auditoria independente de supply chain

**Data de execução:** 21/10/2026 (America/Cuiaba).  
**Implementação-base:** `infra/nivon-cloud-blueprint-20261020`, SHA `a4619bf7ca7cda9bfeb69801fe2a3f09d6eaff1b` (PR #10).  
**PR independente:** #36, branch `audit/supplychain-coverage-20261021`.  
**Resultado:** REPROVADO para homologação de segurança da imagem; a proteção efetivamente **bloqueia** produção diante dos achados conhecidos.

## 1. Evidência real de scan de imagem

[Workflow `NIVON supply chain guard`, run 39592466907](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39592466907):

- `sbom-and-vulnerabilities`: `failure` com exit code `3` deliberado do gate `infra_supplychain`, status `BLOCKED_HIGH_CRITICAL`.
- **46 achados HIGH, zero CRITICAL**; adicionais 64 MEDIUM, 62 LOW e 1 UNKNOWN.
- **108 componentes da SBOM CycloneDX**, dois resultados Trivy; `imagem_arm64_escaneada=false`, `revisao_independente_concluida=false`, `backup_remoto_verificado=false` e `producao_autorizada=false`.
- `detect-secrets`: success para o conjunto escaneado. Gitleaks verde não atesta inexistência universal de segredos.
- `worker-offline` e testes gerais tiveram sucesso em workflows separados no mesmo SHA. Isso **não neutraliza** o bloqueio de segurança. Não é correto equiparar contagem de ocorrências a 46 CVEs distintos ou afirmar exploração sem análise do relatório bruto em ambiente autorizado.
- A imagem de worker é temporária de CI, e não release; o achado bloqueia sua **promoção**, não prova que um sistema vulnerável foi implantado.

## 2. Testes independentes e achados

[Run 39593155613](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39593155613), SHA `5c9bd428c4e70e6684beb37702aadff92e65665a`:

```text
test_controle_scanner_imagem_sbom_coerentes_nao_autoriza_producao ... ok
test_controle_achado_high_bloqueia_sem_go_live ... ok
test_p0_alteracao_inventory_usado_no_docker_dispara_supplychain ... FAIL
test_p1_sbom_da_imagem_incorreta_nao_prova_imagem_inspecionada ... FAIL
Ran 1002 tests in 6.882s
FAILED (failures=2, skipped=6)
```

| ID | Classe | Comportamento demonstrado | Correção exigida |
|---|---|---|---|
| NC-AUD-016 | P0 | `Dockerfile.worker` contém `COPY infra/inventory.v1.json`, mas `.github/workflows/infra_supplychain.yml` não monitora esse arquivo em `on.pull_request.paths`. Uma PR que altere somente esse arquivo pode modificar a imagem sem disparar o scan | Remover filtro seletivo para scanner obrigatório em PR ou cobrir integralmente o grafo de COPY/build context, incluindo `infra/inventory.v1.json`, arquivos de workflow relevantes e regras para alterações futuras |
| NC-AUD-017 | P1 | `avaliar_relatorios` verifica `scan.ArtifactName`, mas não rejeita `sbom.metadata.component.name="outra-imagem:ci"` quando o scan declara `nivon-worker-supply:ci` | Vincular relatório e SBOM ao mesmo digest de imagem/metadata confiável, com rejeição expressa de identidade contraditória e política para metadata ausente |

### Cuidados de interpretação

- Os dois testes são **inteiramente sintéticos**; demonstram lacunas de cobertura e de vínculo entre evidências, não uma violação comprovada do runtime nem bypass já praticado.
- O fluxo CI existente é fail-closed quando Trivy retorna HIGH/CRITICAL, como demonstrado no teste-controle e no escaneamento real. O risco NC-016 é o **gatilho ausente** para determinado tipo de alteração.
- Habilitar somente `infra/inventory.v1.json` resolve o caso testado, mas a política de segurança precisa cobrir também novas dependências e todos os Docker COPY futuros.
- Uma SBOM criada pela mesma execução do Trivy reduz o risco operacional, mas o validador não garante essa relação; exigir a identidade/digest da imagem gera evidência verificável.
- O relatório bruto de vulnerabilidades **não foi publicado nem obtido**. A correção dos 46 HIGH depende de revisão de pacotes, versões e patchability em ambiente autorizado, preservando informações sensíveis.

## 3. Pendências / critérios de aceite

1. PR #10: remover ou corrigir gaps no gatilho do scanner e cross-check de artefatos; retestar exatamente os quatro casos da auditoria em um SHA fixo.
2. Infraestrutura: catalogar os 46 achados HIGH com pacote afetado, versão instalada, versão corrigida, dependência/transitividade, escopo de runtime, priorização e recomendação de mitigação; nunca reduzir o gate ou ocultar achados para obter verde.
3. Verificar escaneamento amd64 e ARM64, proveniência upstream das ferramentas, SBOM assinada e licenças transitivas; realizar avaliação de criticidade independente.
4. Governança: proteger `main` com checks obrigatórios, impedir merge/commit direto sem workflow; relatório anterior constatou `main.protected=false`.
5. Integrar com os bloqueios independentes de fretes (#33), atomicidade e concorrência (#35), integridade editorial (#28), e integração (#13), sem afirmar release operacional.

**Parecer:** não homologar produção, publicação externa nem implantação. A PR #36 contém exclusivamente testes e documentação de auditoria, sem modificar Dockerfile, workflow, scanner ou imagem de produção.
