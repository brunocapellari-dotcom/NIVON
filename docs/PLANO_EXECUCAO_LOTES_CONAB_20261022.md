# NIVON — Plano e execução em lotes: Engenharia de Dados CONAB

**22/10/2026.** Implementação em `feat/dados-lote-conab-endtoend-20261022`, PR #124.

## Priorização oficial de execução

| Ordem | Entrega | Critério objetivo | Status nesta PR |
| --- | --- | --- | --- |
| P0 | Leitura de 3 vintages reais de referência | Hash SHA256 conferido por arquivo e parser sem depender de fixture sintética | EXECUTADO em GitHub Actions (terceiro agrobr) |
| P0 | RAW → parser → normalização → staging | Dados de todas as 3 vintages gravados em transação no SQLite LAB | EXECUTADO, sem banco real |
| P1 | Idempotência e reconciliação | Segunda execução não cria snapshots nem observações repetidas | EXECUTADO no mesmo processo |
| P1 | Auditoria e relatório operacional | Total por competência, cultura, UF, revisões e média de estados, provenance | EXECUTADO, saída JSON somente do QA |
| P1 | Backup/restauração isolada | Cópia consistente e igualdade exata das tabelas e integridade SQL | Implementado em memória, **não** equivale a backup durável |
| P2 | Incremental para origem oficial | Identificar nova edição/competência e baixar apenas novos RAWs com evidência direta CONAB | PENDENTE da conectividade/licença/perfil de coleta |
| P2 | Banco canônico persistente e implantação | Migração shadow transacional, right-to-use, origem comprovada, release gate | BLOQUEADO até fonte real validada e autorização |

## Priorização de testes em lotes

1. **Integração real temporária:** 3 XLSX completos, 3 SHA verificados, parser, staging SQLite e consultas efetivas.
2. **Histórico/oráculos:** 66 observações e 7 culturas na vintage de setembro/2025, competência e valores de cada arquivo, recusa de layout incompatível.
3. **Idempotência e divergência:** segunda execução e detecção de SHA/tamanho/semana/chave repetida.
4. **Falhas e segurança:** HTTPS GitHub limitado ao commit fixo, sem redirects/proxy, sem fallback de WAF ou origem; testado via transport simulado.
5. **Persistência/recuperação:** SQLite de laboratório atomicamente, SQL `integrity_check` e `foreign_key_check`, backup/restauração em memória.
6. **Regressão total:** suíte existente `python -m unittest discover -s tests -v`, sem executar testes unitários por comando separado.

## Evidência da execução observada

[GitHub Actions da primeira execução E2E (run 39890498390)](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890498390) e [CI subsequente aprovada (39890589975)](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890589975).

Foi executado o job `validar-conab-vintages-reais-de-terceiro` no GitHub Actions. O processo baixou **233.194 bytes** de **3 XLSX completos** de `bruno-portfolio/agrobr`, referência fixa Git commit `befb27dd2e9929fab51d0eb308968927fe361840`. As referências são documentos publicados pelo projeto agrobr, NÃO uma coleta autenticada diretamente pelo domínio CONAB. O sistema validou SHA256 e estrutura XLSX e processou:

| Competência | Observações executadas |
| --- | ---: |
| 2025-09-27 | 66 |
| 2026-02-21 | 96 |
| 2026-09-18 | 66 |
| **Total** | **228** |

A primeira execução persistiu 3 vintages num SQLite de laboratório em memória. A segunda execução no mesmo banco não inseriu duplicatas. Os dois jobs da CI foram aprovados após ajustar o teste de delimitação do workflow. Os arquivos foram mantidos apenas em disco temporário do runner e não incluídos em commit, banco de produção ou artifacts.

## Fluxo e execução

`src/nivon/lote_conab_integracao.py` contém o motor completo de laboratório. A rotina usa apenas bibliotecas padrão de Python 3.11.

```sh
# GitHub Actions — somente referência pública congelada e ambiente efêmero
PYTHONPATH=src python -m nivon.lote_conab_integracao \
  --catalogo config/conab_referencias_multivintage_20261021.json \
  --obter-do-github

# Sem rede: usa planilhas previamente disponibilizadas no diretório informado
PYTHONPATH=src python -m nivon.lote_conab_integracao \
  --catalogo config/conab_referencias_multivintage_20261021.json \
  --diretorio /diretorio/absoluto/de/planilhas
```

A execução exige **todas as edições catalogadas presentes e duas ou mais distintas**, abortando quando houver um arquivo ausente ou divergente; obtém os três arquivos integralmente e **só os grava em diretório temporário após a validação de todos os seus SHA**. O staging LAB é materializado apenas após as três passarem pelo auditor; os inserts do lote são protegidos por uma única transação SQLite.

O campo `idempotencia_verificada_na_mesma_transacao` indica teste por repetição *no mesmo banco de laboratório*, não atualização automática ou sincronização no banco NIVON. O campo `recuperacao_lab.backup_restauracao_verificada` indica apenas recuperação entre SQLite temporários. Nenhum desses indicadores é licença nem autenticação da origem CONAB.

## Pendências que realmente requerem outra condição

- **CONAB diretamente:** os bytes do anexo de outubro/2026 seguem inacessíveis via DNS no ambiente conversacional; as referências acima são de terceiro.
- **Permissões e fonte:** avaliar condições de uso do arquivo diretamente no portal antes de ativar coleta/armazenamento/distribuição.
- **Versões e schema:** avaliar repetição com a mesma semana e publicação oficial efetiva; somente então preparar adaptação do banco canônico e backfill autorizado.
- **Serviço recorrente:** planejamento de delta, error budget, scheduler, checkpoint e alertas só após fonte direta auditada e credenciais/infrastrutura aprovadas.

**Gates permanentes:** `fonte_conab_direta=false`, `direitos_homologados=false`, `integracao_banco_produtivo=false`, `migracao_permitida=false`, `publicacao_permitida=false`.

Não converter sucesso de E2E em fixture de terceiro em alegação de integração real de produção. Não mover dados agrobr para o NIVON persistente sem verificação jurídica/operacional.
