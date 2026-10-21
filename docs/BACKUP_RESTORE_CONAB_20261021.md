# NIVON — Backup e teste de restauração dos dois SQLite CONAB

Data de trabalho: 21/10/2026. Escopo: histórico legado semanal CONAB e
ledger NIVON com as tabelas canônicas. Implementação:
`src/nivon/backup_restore_conab.py`, exclusivamente local/offline.

## Problema resolvido

O pré-voo de migração da PR #37 impede a alteração de registros sem
rastreabilidade, mas ainda não garantia uma cópia verificável de
recuperação. O módulo implementa dois procedimentos **separados e
explícitos**: captura de snapshot consistente por banco usando
`sqlite3.Connection.backup` e teste de restauração em diretório novo,
com `PRAGMA integrity_check`, `foreign_key_check`, contagens por
tabela, SHA-256 e comparação bit a bit via hash.

**Advertência de consistência:** os dois bancos são copiados
sequencialmente. A API de backup SQLite é consistente por arquivo e
respeita transações/WAL, mas **NÃO cria um ponto no tempo atômico entre
os dois bancos**. Janelas distintas são registradas para auditoria.
Caso o fluxo demande atomicidade conjunta, será necessário bloquear
escritas ou realizar um protocolo de snapshot coordenado, testado e
registrado fora desta PR.

## Instruções locais

Os caminhos são exemplos: ambos os SQLite devem existir e o destino
de backup/restauração deve ser uma **pasta já criada, vazia e privada**.
Em sistemas POSIX, exigimos `0700` no diretório. Os arquivos escritos
são criados com permissão `0600`.

```sh
mkdir -m 700 /dados/privados/backup-conab-teste
PYTHONPATH=src python -m nivon.backup_restore_conab backup \
  --legado /dados/privados/progresso_legado.sqlite \
  --canonico /dados/privados/ledger_nivon.sqlite \
  --destino /dados/privados/backup-conab-teste

mkdir -m 700 /dados/privados/restore-conab-teste
PYTHONPATH=src python -m nivon.backup_restore_conab restaurar \
  --backup /dados/privados/backup-conab-teste \
  --destino /dados/privados/restore-conab-teste
```

Os SQLite originais são abertos explicitamente em `mode=ro`,
`PRAGMA query_only=ON`. Backup registra `backup_manifesto.json`;
restauração produz `restauracao_verificada.json`. Manifestos não
contêm credenciais, valores das observações ou caminhos originais.

Não há comando de restauração **sobre** um banco existente. Destinos
não vazios, caminhos relativos, symlinks finais e schemas ausentes são
recusados. Nos casos de falha, os arquivos gerados pelo próprio ciclo
são eliminados; nunca apagar conteúdo anterior do usuário.

## Limites do controle

- O hash do arquivo SQLite protege contra alteração acidental ou
  adulteração detectável dos backups; **não substitui assinatura
  digital ou atestação externa de procedência**. Um atacante capaz de
  alterar também o manifesto pode falsificar ambos.
- SQLite armazena dados em claro por padrão. Manter backup e relatório
  **fora do Git**, sob acesso privado, volume criptografado e política
  de retenção estabelecida.
- Uma cópia SQLite **não contém** os bytes RAW CONAB que não estejam
  fisicamente dentro do SQLite; nesta arquitetura o RAW permanece
  externo. É necessário backup próprio do RAW, hashes e trilha
  reprocessável do parser.
- `PRAGMA foreign_key_check` só detecta violações de restrições
  declaradas no schema e não assegura consistência semântica agrícola.
- Restaurar dois bancos corretamente **não implica** que os registros
  legados sejam iguais aos canônicos nem que os datasets estejam
  autorizados para publicação ou comercialização.
- Sem snapshot real autorizado neste PR; testes exclusivamente com
  dados sintéticos. Não há agendamento, envio externo ou migração.

## Próximos gates

1. Auditoria independente de restore com falha injetada, arquivos
   corrompidos, cópia incompleta e cenários WAL de escrita concorrente.
2. Vincular manifesto de backup aos resultados da PR #37 sem
   modificar os bancos de origem; testar restauração repetida sem
   sobrescrever os arquivos.
3. Comprovar `RAW → parser fixado → observações` e licenças por
   operação para edições reais da CONAB.
4. Somente após validação de captura, recuperação, direitos e
   revisão independente, considerar um executor transacional
   idempotente para eventual migração.

Critério de aceitação: CI integral, testes de integridade, SHA
original/restaurado, diretório privado, no-overwrite, e
`migracao_permitida=false` em todas as saídas.


## Verificações de endurecimento após CI inicial

A CI inicial encontrou arquivos auxiliares WAL/SHM persistentes na
pasta de backup. A correção fecha explicitamente conexões e **converte
somente a cópia** para journal mode \`DELETE\` ainda com conexão escritora
ativa; o banco original permanece em \`WAL\`. Isso gera arquivo
restaurável independente dos sidecars, cuja presença residual é uma
falha de regressão.

Também foram endurecidos:
- criação exclusiva \`O_EXCL\` com permissão \`0600\` para arquivos de
  restauração desde o primeiro instante, sem janela inicial \`0644\`;
- recusa de diretório de backup que tenha perdido o modo privado
  \`0700\` desde a captura;
- recusa de SQLite corrompido mesmo se o hash e o manifesto tiverem
  sido ambos reescritos (integrity/schema não dependem só do hash);
- limpeza apenas dos arquivos gerados pelo ciclo, inclusive possíveis
  sidecars \`-wal\`/\`-shm\` em falhas.

A confiança na cópia permanece **local e técnica**: não há
assinatura do manifesto, suporte a snapshots atômicos entre os dois
bancos ou prova de licenciamento/RAW CONAB.
