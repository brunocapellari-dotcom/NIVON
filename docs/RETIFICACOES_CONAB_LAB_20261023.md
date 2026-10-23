# NIVON — Histórico de retificações encadeadas (LAB) — 23/10/2026

Esta entrega dá continuidade à PR #157 por meio da PR #189, com foco em **versionamento de observações corrigidas**, preservação integral de versões, diferenças semânticas, trilha temporal e backups de teste.

## O que foi implementado

- `src/nivon/revisoes_conab_lab.py`: aceita **exclusivamente** manifesto `NIVON_CONAB_RETIFICACOES_SINTETICAS_LAB_V1`. Cada entrada obriga identificar a edição base, o SHA RAW da base, o SHA do predecessor, o SHA dos bytes de revisão, o número de bytes, a competência e a evidência de **simulação laboratorial**. Não existe modo implícito `REAL_AUTORIZADO`.
- Confronta byte a byte SHA/size do XLSX, reexecuta o parser, valida competência, versão do parser, horário de captura estritamente crescente e cadeia linear. Uma mesma competência não pode ter duas revisões concorrentes: qualquer bifurcação ou SHA inesperado é bloqueado.
- Banco SQLite LAB: `lab_retificacoes_conab`, `lab_retificacao_observacoes` e `lab_retificacao_eventos`, com FK, unicidade de predecessor e append-only do fluxo. As tabelas-base `lab_referencia_conab` e `lab_observacao_conab` são preservadas.
- Calcula diferenças a cada transição: observações `alterados`, `incluidos` e `excluidos`. Mudança apenas no arquivo bruto, sem mudança nos dados normalizados, não pode ser classificada como revisão comercial.
- Após inserção, cria backup SQLite **privado e não sobrescrito** `conab-retif-seq-NNNN.sqlite`. Reabre, compara SHA do conteúdo lógico da trilha, `PRAGMA integrity_check` e `foreign_key_check`.
- O sincronizador original `sincronizacao_incremental_conab_lab.py` não pode retornar `SEM_DELTA` sem conferir a integridade da trilha de revisões e seu último backup. A conferência das tabelas-base e seu backup continuam independentes.
- `consultar_versao_asof_lab`: permite selecionar a **versão conhecida até a data/hora de coleta**, sem antecipar uma correção posterior; devolve SHA, revisão e digest semântico. Timestamp de coleta **não é timestamp de publicação**, portanto a saída é sempre `DATA_DE_COLETA_NAO_COMPROVA_PUBLICACAO`, com gates de publicação/migração falsos.

## Evidência e limites da origem

A única base utilizada no ensaio é um arquivo de 11 observações do conjunto de testes público `bruno-portfolio/agrobr`, com semana 07/02/2026. O módulo `fixture_retificacao_conab.py` altera intencionalmente a célula E de percentual no XML OOXML para criar duas versões sintéticas consecutivas.

**Não são correções publicadas pela CONAB.** A simulação serve para testar modelo de armazenamento/versionamento e jamais deve alimentar séries reais de safra ou relatório da operação. Permissão de obtenção/armazenamento/distribuição dos documentos oficiais deve ser verificada separadamente.

## Execução ponta a ponta

`scripts/validar_retificacoes_conab_ci.py` executa com **cinco subprocessos distintos**:

1. Grava a referência original no banco LAB;
2. Aplica a primeira alteração artificial, mantendo 11 observações originais e adicionando 11 na revisão;
3. Aplica a segunda alteração artificial, encadeada ao SHA da primeira;
4. Reexecuta a segunda revisão (sem gravação/backup duplicado);
5. Reexecuta o sincronizador original (no-op), que confere trilhas e backups.

Também consulta três cortes de coleta: antes da primeira revisão, entre as duas e após a segunda. Deve obter sucessivamente `revisao=0`, `revisao=1` e `revisao=2`, com três digests distintos. Verifica 11 observações-base inalteradas, 22 observações de revisões, 2 eventos de correção e **3 backups SQLite de laboratório** (um base, dois de revisão).

Os testes de regressão cobrem rejeição de predecessor incorreto, inversão do tempo, arquivo adulterado, evidência alterada, execução repetida, exclusão de backup e adulteração de observações. Falha em um XLSX do lote impede nova gravação.

## Limitações e próximas etapas

- Backups verificados em **diretório temporário do runner**, não são backups de produção ou de longo prazo, nem objetos armazenados no Google Cloud.
- O histórico é append-only **pelo código testado**; administradores com acesso SQL continuam capazes de alterar linhas. Futura implantação precisa de controles de identidade, imutabilidade/retention, trilha de auditoria externa, teste de recuperação entre ambientes e política de versão do parser.
- **Nenhuma captura direta CONAB, banco produtivo, scheduler, merge ou serviço pago.**
- A fonte oficial precisa ser adquirida diretamente, e revisões reais devem ser verificadas por publicação de origem e direitos de operação antes de habilitar o mesmo modelo para `REAL_AUTORIZADO`.
- A trilha bitemporal completa exigirá quatro datas canônicas e publicação individual homologada quando houver evidência oficial; esta PR só fornece visão **as-of por coleta** e marca as outras incertezas explicitamente.

**Status da PR:** teste no GitHub Actions e documentação; não promover a canônica nem publicar números da simulação.
