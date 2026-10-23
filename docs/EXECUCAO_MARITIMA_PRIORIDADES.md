# NIVON — Execucao dos blocos maritimos

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
