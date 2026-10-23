# NIVON — Plano integrado de execução e testes

**Data:** 22/10/2026 — **escopo:** NIVON (câmbio, mercados e interfaces)
**Execução canônica deste ciclo:** PR #21, base PR #12, demais frentes pelo PR #13.

## Princípios operacionais

1. Avançar **pacotes completos** (coleta/transformação/ledger/consulta/auditoria)
   por ciclo, nunca criar um comando unitário só para completar uma linha.
2. Usar a CI para rodar **testes completos + ensaio ponta a ponta em cada PR**.
   Retestar seletivamente apenas o que falhou durante correções; CI final
   continua abrangente.
3. Executar tarefas reversíveis previamente autorizadas sem pedir permissão
   intermediária, sem merge/deploy/agendamentos comerciais ou custos.
4. Dado observado nunca vira estimativa sem rótulo; fixture não vira REAL.
   Direitos de coleta, armazenamento, derivação e redistribuição separados.
5. Não reutilizar dados estáticos como atualizados nem converter timestamp
   de coleta em horário comprovado de publicação; impedir look-ahead.
6. Não clonar infraestrutura de coletores, snapshots ou bancos entre frentes:
   manter registro canônico e integrar por contratos.

## Prioridade de implementação

| Ordem | Pacote | Status verificável | Gate de conclusão |
|---|---|---|---|
| P0-1 | PTAX: legado + RAW Decimal + coexistência de schemas | **Código e CI aprovados**, sem dado live | E2E e conflitos tratados |
| P0-2 | PTAX: backup, restauração e auditoria de integridade | **Código, testes e recuperação sintética aprovados** | Backup replay contra inventário/SHA |
| P0-3 | PTAX: migração reversa RAW→legado em cópia | **Código e testes aprovados**, só cópia | Bloqueio a precisão não representável |
| P0-4 | PTAX: orquestração de lote atômico e ensaio E2E na CI | **Código e CI aprovados** | Rollback completo em falha intermediária |
| P0-5 | CEPEA, IMEA, CONAB: fontes primárias e atualização incremental | **Outra frente, não homologado aqui** | Autorização, coletor, alterações detectadas, banco e auditoria |
| P0-6 | Fontes argentinas de produção/comercialização | **Outra frente, não homologado aqui** | Origem oficial, cobertura, calendário e revisão |
| P0-7 | PTAX: consulta **real** OData autorizada e direitos ODbL | **Bloqueado pelo catálogo/licença/validação externa** | Payload real + direitos + evidência independente |
| P1-1 | CBOT/ICE e preços físicos com identidade econômica/vintages | Contrato QA em PR #21, licenças e histórico live pendentes | Direitos e séries reais suficientes |
| P1-2 | Fretes divulgados, custos diesel, pressão logística | Frentes próprias; não executar com dados sintéticos como real | Ligação por ponto/rota/transportadora |
| P1-3 | Tendências ALTA/BAIXA/ESTABILIDADE para frete, CBOT e preços físicos | Motor em PR #12; validação com dados reais pendente | Walk-forward, cobertura, calibração e benchmark |
| P1-4 | IVO: explicações auditáveis e briefing via WhatsApp | Integração proibida até gates de direitos/atualidade | Fonte, confiança, referências e licença verificadas |
| P2-1 | Google Cloud: retenção, IAM, observabilidade, custos | Infraestrutura separada; custo/implantação não autorizados neste ciclo | Aprovação e ensaio de restauração |
| P2-2 | Automação de coleta + alertas de desatualização/quebra schema | Preparar em branch, **não ativar sozinho** | Governança da fonte e custo aprovados |
| P2-3 | Homologação integrada e deploy | Não iniciado | Testes E2E reais, segurança e aprovação humana |

## Ordem dos testes — um pacote, uma CI abrangente

| Ordem | Grupo | Evidência requerida |
|---|---|---|
| T0 | E2E completo de dados | Captura→RAW→normalização→ledger→as-of→indicador |
| T1 | Continuidade/DR | Backup→corrupção→restauração→SHA→consulta |
| T2 | Migração bidirecional | Mesmo SHA sem overwrite; RAW-first só em cópia |
| T3 | Adversarial e segurança | WAF/HTML, sem redirect, mídia, duplicações, derechos, tempo |
| T4 | Testes temporais | Revisões, backfill, janelas/cortes, fechamento explícito |
| T5 | Regressão geral | Unittest do repositório, compileall, registro motores |
| T6 | Carga/desempenho | Volumetria/limites documentados; ainda não benchmark live |
| T7 | Aceitação com dados reais | Comparação com fontes oficiais e armazenamento aprovado |
| T8 | Operação/cloud/editorial | Execução monitorada, IAM, custos e direitos de publicação |

## Execução desta rodada

- `src/nivon/continuidade_ptax.py`: inventário de snapshots RAW e
  legados, conferência SHA, vínculos, documentação original quando presente,
  `quick_check`, `foreign_key_check`, pacote SQLite serializado com
  SHA-256, restauração com inventário comparado.
- `src/nivon/ptax_migracao_reversa.py`: constrói **apenas na cópia**
  observações legadas a partir do RAW, sem reclassificar schema ou licenças,
  recusando perdas de casas decimais e discrepâncias em float.
- `src/nivon/orquestracao_ptax_lote.py`: processa 1–20 planos canônicos
  como uma única transação (rollback total, inclusive DDL, em falha).
  A rede segue desligada sem `permitir_rede=True` e direitos.
- `scripts/ensaio_ptax_integrado.py`: **um comando** com 10 etapas
  integradas, acoplado a `.github/workflows/testes.yml`,
  executado em cada PR. Não acessa rede nem grava dados de mercado no
  repositório/Google Cloud.
- Testes: `tests/test_continuidade_ptax.py`,
  `tests/test_ptax_migracao_reversa.py`,
  `tests/test_orquestracao_ptax_lote.py`.
- Evidência da CI integrada:
  https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890476740
  — success, 1.477 testes executados, 5 skipped, 0 falhas,
  ensaio E2E `ENSAIO_PTAX_E2E_APROVADO_APENAS_SINTETICO`.
- Controles de não-publicação continuam obrigatórios
  (`publicavel=false`, `apto_backtest_por_publicacao=false`).

## Dependências legítimas a comunicar ao proprietário

Somente solicitar intervenção para acesso/licença não resolvível
autonomamente, conta externa ou chave necessária, custos/deploy não
autorizados, alteração crítica de política editorial ou homologação
de dado real. De resto, escolher e executar a próxima etapa na
mesma sessão e atualizar este plano no próprio GitHub.

**Nota:** testes de licença/dados reais e tarefas de outras frentes
não podem ser considerados aprovados por um teste sintético bem-sucedido.
Backup em memória **não é** retenção em nuvem, cópia WORM ou recuperação
de infraestrutura externa; executar esses testes somente no ambiente
autorizado após aprovação de acesso/custo.
