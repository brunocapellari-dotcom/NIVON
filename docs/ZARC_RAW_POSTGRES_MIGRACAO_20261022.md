# NIVON — RAW imutável, retenção e ponte ZARC para PostgreSQL

Estado verificado em **22/10/2026 (UTC: 23/10)**. A PR continua em `draft`.

## Implementação

- `src/nivon/zarc_raw_vault.py`: cofre de arquivo **local** endereçado por SHA-256, modo privado 0700/0600, gravação atômica com hard link, sem sobrescrever arquivos existentes, verificação de conteúdo inteiro, sem downloads. Exige edição previamente inserida no ledger existente por `zarc_staging.py`.
- `src/nivon/zarc_postgres_bridge.py`: plano de migração **offline**; revalida SHA do arquivo RAW contra o ledger, confirma a contagem do staging, percorre as linhas originais e emite lotes de até 500 dicionários. Valida o SHA de cada linha e não colapsa dimensões agrícolas repetidas.
- `sql/postgres/002_zarc_mt_staging.sql`: modelo PostgreSQL 17 de staging na schema `nivon_agro_staging`, com tabelas de edições, coletas e linhas MT. **Arquivo SQL não executado em banco remoto.** Uma migração com `CREATE TABLE IF NOT EXISTS` não substitui revisão de schema já existente; executar somente em destino agrícola controlado.
- `tests/test_zarc_raw_vault.py` e `tests/test_zarc_postgres_bridge.py`: verificam idempotência, consistência com ledger, bloqueio de dados reais, symlinks, permissões, corrupção, versão diferente, validadores de lote e integridade do JSON.
- `scripts/ensaio_staging_zarc_sintetico.py` agora exercita staging SQLite, RAW privado, backup/restauração de RAW e SQLite, e emite todos os lotes para futura carga PostgreSQL. **Não executa conexão PostgreSQL nem consulta dados reais.**

## Execução verificada

- [GitHub Actions #39890985643](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890985643): testes RAW aprovados após remover o link temporário antes da verificação de unicidade do inode.
- [GitHub Actions #39891420077](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39891420077): suíte offline com ponte para PostgreSQL passou.
- [GitHub Actions #39891462900](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39891462900): ensaio integrado de **27.918 registros 100% fictícios**, 142 identificadores artificiais, 1 edição, 2 coletas, **27.918 linhas no SQLite restaurado e 27.918 linhas emitidas para futura migração**, RAW de 5.248.998 bytes com SHA-256 `bb7ad196eaa7cb942ac5122fb7cb1837ff1a64033dea35b7f806f3a08cab4bd3`, backup RAW revalidado, SQLite integrity_check OK, duração observada 3,740 s; `postgres_gravado=false`, `carga_ao_banco_real=false`.
- [GitHub Actions #39891466196](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39891466196): suíte geral aprovada na revisão de código.

## Relação com o arquivo oficial

A prova real do CSV completo ZARC 2026/2027 foi concluída anteriormente em [#39854814268](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39854814268): 211.652.014 bytes, 957.490 linhas Brasil, 27.918 linhas MT, 142 municípios, hash `65f52578a4869894311888323d87db75a5452829a3dabef90786f3f14b02d652`. **Isso não significa que o arquivo foi guardado no cofre agora.** O cofre e a ponte PostgreSQL foram validados **com arquivos artificiais**, em runners efêmeros; não há backup durável remoto comprovado.

## Banco do NIVON e limites

A conexão Neon disponibiliza projetos com os nomes `NIVON-PTAX` e `NIVON-PTAX-OPERACIONAL`. Não presume que um banco dedicado a PTAX seja o banco agrícola do ZARC. A migração PostgreSQL está somente no GitHub e **nenhuma operação SQL foi realizada no Neon**.

A consulta a projetos existentes é apenas inventário, não significa quota, preço, região, segurança, IAM ou possibilidade de uso do plano gratuito aprovados para ZARC. Não contratar nem criar projetos sem avaliar quotas e eventual cobrança.

O RAW local pode ser perdido junto com o disco; falta armazenamento externo durável com acesso controlado, backup e restauração sob permissão. O CSV original não deve ser commitado ao GitHub. Os dados decendiais continuam literais, não previsões nem risco percentual.

## Próximos gates

1. Designar um destino agrícola de banco (não escolher automaticamente PTAX), confirmar orçamento/quotas, permissões, localização regional, esquema existente e eventual retenção em objeto durável.
2. Comprovar direitos de coleção, armazenamento, atribuição e política de uso específicos do ZARC 2026/27; registrar evidência verificável.
3. Validar interpretação metodológica dos decêndios, portarias e cruzamento territorial IBGE/SICOR, sem inventar datas de publicação anteriores à coleta.
4. Fazer **uma carga real controlada** do arquivo original com mesmo SHA em staging privado, ativando os gates canônicos somente após aprovação e rastreabilidade; validar as 27.918 linhas e reconciliar agregados com prova original.
5. Implementar carregador PostgreSQL autenticado, transacional, com COPY/upsert seguro e limitação de custo; testar rollback, restauração RAW e backups em ambiente escolhido.
6. Somente depois, habilitar monitoramento por diferenças e agendamento. Código existente NÃO é serviço operando.

Estado: **RAW_LOCAL_E_PONTE_POSTGRES_TESTADOS_COM_SINTETICOS**, sem implantação em produção.
