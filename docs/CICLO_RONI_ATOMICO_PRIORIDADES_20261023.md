# NIVON | Entrega de ciclo de atualização meteorológica RONI
**Referência de implantação:** 23/10/2026. **Estado:** testado localmente em CI, **ainda não integrado à main**, nenhum serviço/cron pago ativado.

## Roadmap de execução por lote

| Ordem | Atividade de produção de código | Aceite integrado | Estado |
|---|---|---|---|
| P0 | Importação incremental RONI, RAW por hash e SQLite | Dois arquivos num ciclo, replay idempotente, reinício | Implementado PR #129 |
| P0 | Transação atômica de múltiplos snapshots | Falha no terceiro arquivo reverte os anteriores, sem resíduos RAW | Implementado nesta PR |
| P0 | Verificação de edições versus instante local conhecido | Comparação duas últimas versões distintas, retorno a edições antigas sem apagar história | Implementado nesta PR |
| P0 | Backup/restore verificável e independente | Cópia consistente SQLite+RAW, manifesto de hashes, auditoria e recusa de corrupção | Implementado nesta PR |
| P0 | Comandos únicos e validação completa | CLI `validar/executar/relatorio/backup/validar-backup/auditar`, suíte total CI | Implementado nesta PR |
| P0 | Não contornar veto de fonte no modo HTTPS | Catálogo CANDIDATE/OFF impede comando `capturar` antes mesmo de criar DB | Implementado nesta PR |
| P1 | Primeiro RAW oficial NOAA CPC com data e proveniência | Resposta HTTPS real, cabeçalhos, SHA, conteúdo completo, fonte e direitos | **Bloqueio externo: DNS e autorização** |
| P1 | Avaliação de disponibilidade point-in-time histórica | Snapshots guardados na data real da captura e publicação auditada | Ainda sem arquivos históricos autenticados |
| P1 | Consolidação de PRs da frente na integração central | Revisão linear #68→#81→#89→#116→#129→esta PR | Pendente de coordenação de merge |
| P2 | Agendamento real incremental sem excesso de downloads | Direitos por operação e licenciamento, persistência/restauração homologada, fonte atualizada | NÃO agendado |
| P2 | Aferição meteorológica fora da amostra | ENSO, MJO/RMM, INMET, NASA POWER, NWP, previsão de chuva e vazão com hindcasts reais | Depende da disponibilidade real |

Os testes são de integração do código e operação, sem prova de habilidade preditiva; os 5 testes ignorados em CI são inspeções externas intencionalmente desligadas.

## O que foi integrado na PR

- `src/nivon/roni_store.py`: substituição de commits por `savepoint_atomico` em escritas para permitir ciclo maior com rollback. Validação formal do hash do índice antes de acessar RAW.
- `src/nivon/roni_ciclo.py:processar_ciclo_roni`: sequencia 1–50 edições já analisadas em uma transação SQLite; após cada lote, audita todos os RAWs e valores. Se algum passo falhar, reverte o banco e remove **somente** artefatos novos órfãos do lote. Diretório RAW deve ser dedicado a esse acervo e acesso dos escritores precisa ser serializado.
- `relatorio_revisoes_roni`: em `corte_em`, seleciona as duas versões distintas historicamente **registradas no NIVON**, indicando competência atual, alterações quantitativas, máximo desvio de revisão e índice SHA; nunca presume quando cada estação histórica foi publicada pela NOAA e não traduz ENSO em probabilidade agrícola.
- `gerar_backup_roni`: exporta SQLite por backup consistente, copia RAW por SHA para diretório novo, verifica tudo e gera `manifesto_backup.json`. O destino não pode existir. `validar_backup_roni`: verifica hash SQLite, todos os SHA RAW, cada valor normalizado e resumo do manifesto.
- `roni_cli.py`: modos `relatorio`, `backup`, `validar-backup` agregados aos comandos existentes; `executar` agora é atômico.
- `roni_captura_manual.py`: execução **real**, sem transporte simulado, verifica `NOAA_ENSO_RONI` em `config/fontes_nivon_master.v1.json` e bloqueia enquanto `CANDIDATE`, `enabled=false` ou `collection_authorized=false`. Uma string de licença no comando não altera esses gates. O catálogo atual proíbe operações reais em todos os datasets.

## Comandos para operação LOCAL, sem rede

Pré-condição: os arquivos RONI sintéticos/autorizados e `lotes.json` precisam existir, conforme documentação da PR #129.

```bash
PYTHONPATH=src python -m nivon.roni_cli validar --manifesto lotes.json
PYTHONPATH=src python -m nivon.roni_cli executar --manifesto lotes.json --banco roni.sqlite --raw-dir arquivo_raw --confirmar-gravacao-local
PYTHONPATH=src python -m nivon.roni_cli relatorio --banco roni.sqlite --raw-dir arquivo_raw
PYTHONPATH=src python -m nivon.roni_cli backup --banco roni.sqlite --raw-dir arquivo_raw --destino-backup backup_001
PYTHONPATH=src python -m nivon.roni_cli validar-backup --destino-backup backup_001
```

Nenhum desses comandos exige ativar acesso HTTP, conectar serviços pagos ou fornecer segredos. `capturar` com HTTP não será autorizado enquanto a fonte não for homologada pelo catálogo mestre. O código não tem cron nem atualizador automático no Google Cloud.

## Evidências necessárias antes de tornar operacional

1. **Direitos**: fonte e operações autorizadas; revisar condições de ingestão, armazenamento e eventual republicação por produto.
2. **RAW original**: resposta HTTPS real integral, MIME, relógio confiável, SHA, metadados de obtenção; conexão DNS disponível. Testes com transporte falso não substituem captura real.
3. **Origem temporal**: recuperar snapshots *reais* de épocas anteriores quando for estudar habilidade retrospectiva. O arquivo atual com números de 1950 em diante não constitui uma série de vintages de publicação de 1950 em diante.
4. **Confiabilidade do acervo**: executar backup e restore em storage persistente, testar permissão de escrita, exclusão/acesso e monitoramento; controlar concorrência entre escritores.
5. **Governança de integração**: conciliar PRs filhas e revisões centrais uma única vez, sem reintroduzir parsers científicos de #9/#11.

**Resultado correto:** código operacional local e teste de integridade aprovado, mas previsão/ingestão e publicação de dados reais NÃO homologados.
