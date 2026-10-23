# NIVON — Execucao dos blocos maritimos

> **ARQUITETURA ATIVA A PARTIR DE 23/10/2026: GOOGLE CLOUD.** O plano de
> persistencia Neon descrito abaixo pertence ao historico anterior e foi
> substituido. A arquitetura atual esta documentada em
> infra/google_cloud/README.md, com o gravador BigQuery, Cloud Storage,
> Cloud Run Jobs e Cloud Scheduler. O workflow de coleta/Neon foi removido
> do GitHub Actions. Recursos GCP nao foram implantados nesta rodada.
> Nao habilitar NIVON_MARITIMO_DSN ou o cron antigo.

Estado: implementacao de persistencia LOCAL versionada e fluxo de QA. Nao significa
coleta homologada, continuidade do banco no cloud ou AIS real operacional.

## Backlog executavel

1. P0 Integrar fonte HTTPS publica -> parser existente -> capturas (SHA256) ->
   revisoes/atuais SQLite; impedir que CDP seja publicado sem comparador.
2. P0 Persistencia permanente em banco NIVON (Neon/Postgres) via credencial em
   secret vault, com migracao versionada e auditoria de dados de terceiros.
3. P0 Inventariar geocercas verificadas, depois consumir eventos AIS reais do
   monitor do NIVON; nao inferir tonelagem ou operacao concluida.
4. P1 PortWatch (agregado, nao line-up), autoridades Suez e Panama, Argentina.
5. P1 Frequencia/alertas por fonte somente apos testes com resposta real.

## Evidencia de testes exigidos

- Parse e captura repetida -> sem duplicatas.
- Mudanca de status programado -> atracado informa revisao, nao realizado.
- Fonte vazia e CDP divergente -> quarentena sem apagar estado valido.
- AIS com duas visitas separadas -> duas evidencias inferidas, nenhuma tonelagem.
- Reiniciar processo SQLite -> historico consultavel.

## Acionamento

`PYTHONPATH=src python -m nivon.maritimo_pipeline --fonte suape --arquivo-html entrada.html --banco maritimo.sqlite`

Para rede, trocar `--arquivo-html` por `--permitir-rede` quando permissoes da fonte
forem verificadas. O workflow tem agendamento 6h com gate na variable
`NIVON_MARITIMO_COLETA_HABILITADA`; o historico do runner e EFEMERO.
Nao habilitar agendamento como producao sem banco permanente, captura
de erros/freshness, direitos de uso e verificacao de parsing ao vivo.

A programacao CDP permanece em quarentena por politica mesmo atual;
GPV Ponta da Madeira requer arquivo/acesso autorizado; o terminal publico
de Itacoatiara e Amaggi sao entidades distintas.

## Neon integrado

Schema `nivon_maritimo` criado no projeto conectado NIVON (NIVON-PTAX-OPERACIONAL), sem tocar nas tabelas CEPEA, IMEA, CONAB ou PTAX. Migracao versionada em `migrations/001_maritimo_neon.sql`. Adaptador `maritimo_neon.py` faz UPSERT parametrizado por hash/revisao, na mesma transacao de cada sincronizacao; nao registra dados sinteticos no banco de producao.

A coleta agendada so inicia quando a variavel `NIVON_MARITIMO_COLETA_HABILITADA` for habilitada e o secret `NIVON_MARITIMO_DSN` estiver configurado. Ate la, nao ha alimentacao online do banco. Nao imprimir DSN.

**PortWatch:** variável normalizada `volume_transito_estimado_t` estima cargo em trânsito, não volume oficial realizado. A coluna legada `capacidade_proxy` é mantida para compatibilidade e documentada como tal.

## Rodada de 23/10/2026 — execução integrada

Implementados `src/nivon/maritimo_lote.py`, `tests/test_maritimo_lote.py` e o
sincronizador Neon ampliado: coleta das quatro fontes HTML em **um lote**,
falha isolada por fonte, estados OK/QUARENTENA/FALHA, captura/revisões
idempotentes, registro em `lote_execucoes` e sincronização transacional com
`nivon_maritimo.coleta_execucoes`.

O GitHub Actions deixou de executar quatro comandos autônomos com resultado
agregado inconsistente: usa agora `python -m nivon.maritimo_lote`. Em execução
agendada, preserva falhas e quarentenas no banco (quando DSN estiver
configurado), **sem mascarar a falha final de saúde**. A periodicidade configurada
é a cada seis horas, mas a coleta permanece bloqueada pela variável
`NIVON_MARITIMO_COLETA_HABILITADA` e depende do secret
`NIVON_MARITIMO_DSN`. A coleta PortWatch é um gate separado
`NIVON_PORTWATCH_COLETA_HABILITADA`.

**Dados reais sem persistência:** job read-only de Imbituba extraiu 5 linhas
em 23/10/2026; job read-only PortWatch obteve 32 observações de
09–16/10/2026 nas passagens Hormuz, Bab el-Mandeb, Suez e Panamá.
Essas consultas **não constituem execução de coleta periódica nem carga
no Neon**.

- Imbituba + QA: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944614808
- PortWatch + QA: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944766718

Conexão existente do AISStream (motor reutilizado de AgroLog) foi compatibilizada
com o importador Itacoatiara: recebe eventos normalizados `observed_at`,
MMSI e posições; geocercas auditadas obrigatórias. Sem geocerca e cobertura
verificadas, não há escala confirmada no terminal Amaggi.

**Banco operacional preparado:** schema `nivon_maritimo` com capturas,
escalas_revisoes, fluxos_passagens e coleta_execucoes; a view
`nivon_maritimo.estado_fontes_v` mostra o último estado e frescor por fonte
(apenas após as primeiras gravações reais). Migrações `001`, `002` e `003`
aditivas no repositório.

### Próximo lote P0 — não marcado como concluído

1. Vincular `NIVON_MARITIMO_DSN` a segredo protegido de Actions com
   privilégios mínimos; não colocar conexão ou senha em comentários/chat.
2. Ativar a coleta apenas depois de conferir consentimento, alcance das
   URLs e ingestão `HTML → parser → execuções → Neon → view`, com
   amostra real por fonte, sem converter line-up programado em realizado.
3. Confirmar Suape e CDP em inspeções controladas, corrigindo
   redirecionamentos e HTML dinâmico sem contornar autenticação.
4. Auditar geocercas do terminal público de Itacoatiara e Amaggi, validar
   AIS com posições reais, medir interrupções e divergências.
5. Incorporar GPV autorizado de Ponta da Madeira e fontes portuárias
   remanescentes à rotina cron; homologar alertas e ETA sobre histórico.
6. Integrar a branch marítima empilhada até main sem force-push,
   duplicar modelos ou incorporar blocos fora dos testes de regressão.

**Status honesto:** código e schema preparados, duas fontes verificadas
em leitura real, CI sintética aprovada. Zero evidência de cron produtivo
alimentando Neon; zero evidência de line-up inferido Amaggi com AIS real.
