# NIVON — Lote incremental e recuperação da CONAB (23/10/2026)

PR #157, empilhada na PR #124. **Escopo:** laboratório persistente local sobre XLSX históricos públicos de terceiro, não produção e não ingestão direta CONAB.

## Avanço implementado

O `src/nivon/sincronizacao_incremental_conab_lab.py` usa o histórico SQLite existente para planejar o delta por ID canônico de referência, competência e SHA bruto. Faz GET **somente dos arquivos novos** no commit GitHub imutável documentado do `bruno-portfolio/agrobr`, ou recebe planilhas locais com mesmo SHA. Reexecuta o parser OOXML, verifica contrato, semana, contagem/oráculo, normaliza, grava observações e evento de processamento em uma transação SQLite privada.

Quando nenhuma edição muda, a reexecução **não faz requisições de rede, não insere registros, não cria novo backup**; ainda confere integridade das linhas armazenadas e do backup mais recente. Se ID/SHA muda, a mesma semana reaparece com outro SHA ou o parser instalado diverge da versão gravada, falha com conflito em vez de sobrescrever vintage. O histórico não é apagado por ausência de edição do catálogo atual.

A implementação mantém os seguintes estados **sempre falsos**:
- `fonte_oficial_conab`: os RAWs são referências de terceiro, não coleta independente do domínio CONAB;
- `direitos_uso_auditados`, `migracao_permitida` e `publicacao_permitida`;
- nenhum coletor recorrente, banco canônico, serviço Google Cloud, notificação ou release foi ativado.

## Persistência e segurança

- SQLite de laboratório em pasta privada `0700`, arquivo iniciado em `0600`, `foreign_keys=ON`, `synchronous=FULL`.
- `lab_referencia_conab`: referência imutável, SHA bruto, parser SHA, competência, tamanho semântico e origem.
- `lab_observacao_conab`: observações normalizadas de cada SHA; mantidas isoladas de dados produtivos.
- `lab_integridade_observacoes`: SHA-256 semântico do conteúdo armazenado, permitindo detectar modificações ou supressão de linhas antes de aceitar `no-op`.
- `lab_eventos_incrementais`: trilha de ciclos com horário de execução, SHA do catálogo e contagens.
- Backup SQLite completo após cada rodada com mudança; arquivo privado individual, não sobrescrito, reaberto em leitura com `integrity_check`, `foreign_key_check` e comparação do conteúdo lógico com o banco vivo. Um `no-op` exige o último backup íntegro e equivalente.
- Os backups da CI residem **somente no runner temporário** e são eliminados no fim. Embora sejam arquivos SQLite consistentes em disco durante a execução, **não representam backup operacional durável** para Cloud/produção. Precisam posteriormente de storage autorizado, retenção e recuperação real.
- Sem permissão para modificar tabela canônica do NIVON; em laboratório apenas.

## Evidências da execução no GitHub Actions

[CI de integração](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946190758): o job E2E passou e baixou efetivamente os XLSX de referência de terceiro. A regressão inicial encontrou um erro de fixture de revisão (duas competências iguais no mesmo catálogo), corrigido para testar revisão contra **banco já persistido**, e não duplicidade inválida dentro do catálogo.

[CI final com guarda semântica](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946507730): ambos os jobs concluíram com sucesso, **1.367 testes executados, 5 ignorados e 0 falhas**, incluindo arquivos de terceiro reais e smoke de três processos independentes.

| Processo independente | Arquivos requisitados | Vintages novas | Observações adicionadas | Total armazenado |
| --- | ---: | ---: | ---: | ---: |
| 1 — carga inicial | 2 | 2 | 162 | 162 |
| 2 — delta | 1 | 1 | 66 | 228 |
| 3 — sem novidade | 0 | 0 | 0 | 228 |

Duas rodadas com escrita geraram dois backups privados distintos, abertos e testados. A terceira não solicitou rede nem backup. O banco final possui 3 referências, 228 observações e 2 eventos. Os hashes originais dos três XLSX foram verificados antes de processar dados.

## Pacote de testes por lote

1. **E2E com dados de terceiro não sintéticos**: cada ciclo executa um novo processo Python com banco SQLite persistente, comparando 2→3→3 vintages e 162→228→228 observações.
2. **Incremental verdadeiro**: contagem de downloads 2→1→0 e preservação do histórico.
3. **Consistência de revisão**: alteração de SHA/ID e competência repetida são colocadas em quarentena, sem sobrescrita.
4. **Atomicidade**: trigger de falha em evento força rollback de todas as novas observações do lote.
5. **Integridade/recuperação**: reabertura de backup, conteúdo comparado, adulteração de observação, exclusão de linha e ausência de backup bloqueiam execução.
6. **Regressão geral**: toda suíte NIVON na mesma execução, sem chamadas manuais por teste.

## Pendências reais antes de produção

P0: baixar pelo menos uma edição **diretamente** do domínio CONAB em ambiente autorizado, registrar captura HTTPS real e direitos por operação; resolver divergências de formato, autoria e vigência. O laboratório agrobr não substitui esta etapa.

P1: criar fluxo de **revisão explicitamente versionada** com vínculo ao SHA anterior, evidência da retificação e proibição de apagar original; preparar suporte a retenção/backup em storage autorizado com restore a partir de processo isolado.

P1: conectar o pipeline aprovado ao banco transacional canônico após migração shadow, reconciliação e auditoria de direitos e proveniência. O modo `REAL_AUTORIZADO` continua bloqueado.

P2: planejar agenda incremental, política de retries e alertas por fonte após a execução de coleta real, respeitando frescor e calendário de publicação. Não iniciar cron nem custos antes da validação.

**Conclusão:** há um sincronizador incremental real e reprodutível **para referências históricas de terceiro**, com persistência SQLite local e recuperação testada. Ainda **não** há coletor CONAB produtivo, direitos homologados ou dados oficiais de outubro integrados ao banco principal.
