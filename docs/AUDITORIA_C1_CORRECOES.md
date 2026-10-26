# NIVON — Registro de correções de auditoria C1

Referência: Claude C1 (25/10/2026), revisão cruzada Gemini/Grok, commit inicial main 4e59fa2.

## Código aplicado em branch (NÃO HOMOLOGADO)

- C1-05: status parcial reprovado antes do arquivo GCS/MERGE, stage e manifesto obrigatórios na coleta recorrente.
- C1-06: SHA-256 recalculado sobre os bytes RAW efetivamente baixados; conferência em recuperação e ao reutilizar/upload de RAW.
- C1-07: staging BigQuery com expiração seis horas; job_id e num_dml_affected_rows retornados, sem assumir que linhas enviadas foram inseridas.
- C1-08: migração Neon com somente INSERT após preflight de conflito de mesma chave/vintage; bloqueia divergência antes do MERGE.
- C1-09: função PTAX no código admite somente main e evento agendado/manual; requer implantação da função no Neon para alterar o serviço.
- C1-10: DDL inclui filtro obrigatório de partição.
- C1-07/14: workflow que tentava habilitar APIs GCP com identidade do coletor substituído por aviso sem OIDC e sem escrita.

## Evidência necessária para mudar status para RESOLVIDO

1. GitHub Actions da PR: suíte completa aprovada na revisão final (CI offline não comprova nuvem).
2. Proteção real da main, restrições de OIDC/WIF e identidades separadas, verificadas via GitHub/GCP.
3. Uma execução de replay real com confirmação de hash de cada RAW, DML e readback, só após licença e orçamento aprovados.
4. Deploy autorizado da função PTAX no Neon, com teste negativo na branch legada e teste positivo do evento schedule.
5. Reconciliação da migração Neon GCP em duas datas, backup + teste de restauração; Neon permanece ligado.
6. Auditoria de preço/custo e retenção para downloads integrais de RAW, e de leitura de objetos pelas service accounts.

## Itens que não são resolvidos por esta PR

- C1-01: branch protection/rulesets exigem alteração administrativa.
- C1-02/03: IAM, WIF e separação de identidades precisam de verificação e aprovação no Google Cloud.
- C1-04/11: nenhum ciclo de ingestão contínua GCP está homologado; desenvolver recibos de execução e monitor de dados.
- C1-12/13: reconciliação das linhagens antigas e desduplicação/serialização de todos workflows por escritor.
- C1-15/18: IVO e agentes Claude/Codex em branches antigas ainda não integrados.
- Gemini/Grok: curvas, basis, consenso, margens, radar, cockpit web e modelos probabilísticos permanecem roadmap de produto.

A branch não autoriza ativar escrita, desativar Neon, ampliar IAM nem habilitar Cloud Run/Scheduler.
