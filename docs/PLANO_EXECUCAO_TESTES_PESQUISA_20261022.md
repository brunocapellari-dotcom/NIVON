# NIVON — Plano de execução e testes em blocos

**Data de corte:** 22/10/2026 · **Frente:** Pesquisa, Ferramentas e Inovação · **PR:** #27 (draft) · **Custo:** zero/mínimo autorizado.

## Regra operacional

Um único comando do usuário (`continua` ou equivalente) autoriza **vários avanços reversíveis em sequência** dentro da frente, até terminar o bloco ou surgir impedimento real. Cada bloco: recuperar HEAD e CI do GitHub → conferir sobreposição com PRs dependentes → implementar vários componentes relacionados → executar E2E na CI → corrigir falhas → registrar hash de commit, run e artefato → atualizar próximos blocos. Não solicitar comando por teste unitário. Não promover resultado sintético a prova externa. Não fundir em `main`, fazer deploy, consumir serviço pago nem instalar novos terceiros sem segurança/homologação compatíveis.

## Backlog priorizado de execução

| Ordem | Entrega executável | Critério objetivo / testes agrupados | Situação na PR #27 |
|---|---|---|---|
| P0.1 | Sincronizar base IVO e isolar mudanças de pesquisa | Diff por caminho; merge de dois pais sem sobreposição/force; CI verde em HEAD | Feito na base auditada em 22/10 |
| P0.2 | Orquestrar auditoria completa da cadeia local | Wheels fictícios → RECORD/SHA256 → lock → scan **simulado** → Requires-Dist → licença → gate de liberação | Implementado no `pipeline_evidencias_e2e` |
| P0.3 | Executar cenários adversariais no mesmo fluxo E2E | Rejeitar wheel adulterado e relatório com cobertura parcial, inclusive se digest autodeclarado for recalculado | Implementado, executado |
| P0.4 | Gravar evidências inspecionáveis e reutilizáveis | Persistir lock, wheels sintéticos, metadata JSON, report JSON, resumo, SHA256 e ZIP sintético; publicação Actions (3 dias) | Implementado |
| P0.5 | **Reexecutar auditoria com CLI independente** sobre os próprios arquivos gerados | `python -m nivon.auditoria_artefatos_pacotes` não pode retornar aprovação de instalação/produção; `sha256sum -c` deve passar | **Concluído e executado — CI #39890125016** |
| P0.6 | Demonstrar proveniência da execução já feita | Confirmar `run_id`, `commit SHA`, `artifact_id`, digest e arquivos reais disponíveis via API GitHub | **Concluído no nível HTTPS/API+digest; sem assinatura Sigstore** |
| P1.1 | Resolver dependências PEP 508/440 completas e registrar origem de wheels | Lock independente/reproduzível, transitivas e extras, hashes de índice, compatibilidade de tags e licenças; processo autorizado | **Bloqueado:** depende de baixar/instalar ferramentas externas homologadas e executar em ambiente isolado |
| P1.2 | CVEs atuais e SBOM verificados | Scanner real pinado, tempo de corte, advisory primário, SBOM package/file digests, falha fechada | **Bloqueado:** ausência de scanner/artefatos reais aprovados |
| P1.3 | Atestação criptográfica de artefato e verificação | `actions/attest` com OIDC, signature verification por repo/workflow/commit, cadeia de origem e digest do ZIP *interno* | Workflow manual sintético preparado em PR; necessita estar na branch padrão após homologação |
| P1.4 | Testar adaptadores opcionais com bibliotecas de verdade | Instalação isolada, imports, contratos, desempenho, licença e regressões; sem deploy | Não autorizado até P1.1–P1.3 |
| P2.1 | Benchmark funcional de conectores (dlt × nativo) | Fonte pública licenciada, mesmo recorte, tempo/memória, retries, idempotência, operação de custo mínimo | Pendente; instalar dlt exige homologação |
| P2.2 | Integrar com PRs de infraestrutura/dados e automatizar | Contratos versionados, migrações reversíveis, CI completa, homologação de deploy e monitoramento | Pendente de P1 e coordenação de PRs |

## Matriz de testes por rodada

1. **Static/contratos:** `compileall`, metadados de fontes, escopos, registros e dependências declaradas.
2. **E2E positivo:** gerar bytes locais e processar cadeia pela própria API interna. Verificar contagens, SHA256, `RECORD`, license files, grafo e campos `false` obrigatórios.
3. **E2E negativo:** adulterar bytes após criar lock; truncar relatório e atualizar hash no metadata. Ambos devem **falhar** no auditor.
4. **Reprodução por CLI:** salvar todos os insumos, reexecutar `auditoria_artefatos_pacotes` sobre eles, conferir `approved_for_install=false`, `approved_for_production=false` e checksums no shell.
5. **CI/artefato:** Actions concluído em sucesso no SHA da PR. Confirmar artefato `nivon-integracao-e2e-sintetica`, run/ID, tamanho e digest publicado, sem confundir ZIP externo de Actions com ZIP interno de proveniência.
6. **Gate de produção:** continuará `BLOCKED` até autenticação da origem, varredura CVE real, licenças legais, resolução transitiva e smoke-tests instalados.

## Referência de evidências e restrições

- CI inicial E2E com artefato **real de GitHub Actions**: [run #39889893914](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39889893914), artefato `nivon-integracao-e2e-sintetica` ID **12474262474**, digest SHA256 do ZIP externo publicado pela API. Conteúdo **100% sintético**; nenhum artefato de biblioteca externa foi autenticado. Esses identificadores são dados observados no GitHub, não garantias para runs futuros.
- Todos os auditores de pacotes sob esta PR devem manter `approved_for_install=false` e `approved_for_production=false`. A relação de saída de um scanner **simulado** com `tool=pip-audit` é só um fixture de contrato; não atribuir execução real ao scanner.
- **Próximo bloco realmente destravado:** vincular os manifests E2E à proveniência GitHub e planejar o primeiro teste read-only de metadados de pacotes externos em ambiente homologado, sem instalações. Preparar e submeter revisão do workflow de atestação antes de qualquer ativação na branch padrão. Não abrir novos miniprojetos de testes unitários antes de concluir um bloco operacional.

## Continuidade autônoma

Quando uma etapa for concluída, passar diretamente à próxima dependência reversível. Se a base IVO/PR #7 avançar, comparar diffs e reconciliar com segurança antes de prosseguir. Só pedir intervenção do usuário para gasto, segredos, autorização material de software externo, mudanças irreversíveis, deploy ou homologação/merge na branch principal.

## Evidência P0 atualizada — execução independente real em 22/10/2026 (23/10 UTC)

- Commit executado: `8135a8231f20da4e3de720ee84b48ade0c7763e6`.
- [GitHub Actions #39890125016](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890125016): **SUCCESS**. Workflow executou a CLI operacional de auditoria `nivon.auditoria_artefatos_pacotes` sobre **arquivos reais gerados pela própria CI** (mas dados de pacotes 100% sintéticos).
- Artefato [nivon-integracao-e2e-sintetica #12474715806](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890125016/artifacts/12474715806) com 6.288 bytes e digest SHA256 do ZIP de distribuição do Actions `213892547442b11e15dcb2360681d9bbf51f077868ff6e6bf31b30f41ea4124f` declarado pela API do GitHub.
- **Verificação independente após download:** o arquivo ZIP foi obtido pela integração GitHub em uma sessão separada do runner. SHA256 calculado dos bytes baixados = SHA256 da API. Nove arquivos inspecionados e **6 linhas em `sha256sums.txt` recalculadas e aprovadas**. O JSON `resumo_integracao.json` registra 2 wheels fictícios processados, 2 dependências suportadas verificadas, 2 arquivos de licença fictícios, falha fechada para adulteração de wheel e relatório incompleto; ambos `approved_for_install=false` e `approved_for_production=false`. O JSON `resultado_cli_auditoria.json` da CLI independente confirmou as mesmas contagens e bloqueios.
- **Interpretação:** esses são artefatos reais da execução GitHub Actions e validações independentes de integridade dos bytes, **não** resultados externos reais de packages/dados de produção. Nenhuma assinatura Sigstore, atestação SLSA ou conexão a serviço externo de CVEs foi verificada.
- P0.2–P0.6 concluídos dentro do escopo sintético e de integridade do artefato. P1.1–P1.4 permanecem bloqueados pelas dependências materiais descritas na matriz.

