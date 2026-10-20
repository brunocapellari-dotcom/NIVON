# NIVON Editorial Intelligence — Pré-homologação do resumo estratégico
**Data de corte:** 20/10/2026  
**Estado:** implementação em branch de desenvolvimento; **sem go-live, scheduler, coleta ativa, transmissão nem autorização de uso de dados privados**.

## Diagnóstico no GitHub
- \`main\` contém apenas \`README.md\`, com aviso de não homologação.
- PR #8 contém \`rss_radar\`, \`curadoria_radar\`, \`historico_noticias\`,
  \`pipeline_briefing\`, \`briefing_diario\`, \`briefing_composto\`,
  \`outbox_whatsapp\` e CLI de geração offline.
- PR #13 integra regressões entre as 14 frentes e corrige casos de data antiga
  e Sorriso–Dom Aquino; esta branch é **incremental e derivada do PR #8**.
  Reconciliação obrigatória antes de integrar as duas PRs.
- O código existente renderizava \`BRIEFING ESTRATÉGICO\` e campos de impactos;
  a formatação nesta branch usa o título editorial aprovado
  \`RESUMO ESTRATÉGICO DO AGRONEGÓCIO\` sem seção de impactos.
- Nenhuma declaração de fechamento recente prova **última sessão concluída**.
  A validação de fechamento exige edição/sessão da fonte e calendário externo.
- Frete municipal agregado é proibido; pontos de embarque e transportadoras
  permanecem separados. Volume de referência não é viagem realizada.

## Componentes implementados nesta branch
- \`editorial_preflight.avaliar_previa_editorial\`: gate offline, determinístico,
  fail-closed, sem serviços de rede, agendamento ou acesso ao WhatsApp.
- \`scripts/validar_briefing_offline.py\`: consome TXT e auditoria do gerador
  existente mais evidências estruturadas externas; imprime relatório JSON;
  retorno 0 significa somente **apto à revisão**; retorno 2 significa bloqueio.
- \`briefing_diario\`: nome e política editorial aprovados.
- \`briefing_composto\`: contempla Sorriso–Rondonópolis, Sorriso–Dom Aquino,
  Sinop–Miritituba, e referências para Paranaguá, Santos e Uberaba;
  se volume t/dia estiver presente, exige classe OBSERVADO, REFERENCIA ou
  ESTIMADO e torna o rótulo visível; nenhum volume é preenchido artificialmente.
- Regressões sintéticas: janela de 24h inclusive borda exata, offset horário,
  publicação original verificada, URL/evento repetido, rights/sha, preço e
  variação percentual, sessão do último fechamento, volume de referência,
  rotas, proibição de média municipal, hash imutável do texto e estado sem envio.

## Contrato das provas editoriais
A automação não deve inferir \`direitos_publicacao\`,
\`publicacao_original_verificada\`, \`fechamento_confirmado\` ou
\`ultima_sessao_concluida\` a partir do texto, RSS, LLM ou data de coleta.
Esses campos vêm de registros **independentes e auditados**:
- Para todo registro: \`fonte_id\`, \`sha256_origem\`, \`publicado_em\`,
  \`coletado_em\`, \`direitos_publicacao=true\` e
  \`evidencia_direitos_id\`; horário ISO-8601 com offset.
- Notícias: \`titulo\`, \`url\`, \`evento_id\`,
  \`publicacao_original_verificada=true\` e publicação original dentro
  de **[geração−24h, geração]**. Data \`updated\` não renova matéria.
- Cotações: \`grupo\`, \`titulo\`, \`valor\`, \`unidade\`, \`natureza\`,
  \`competencia\`, \`referencia_em\`; Chicago, ICE e câmbio exigem
  \`sessao_fechamento\`, \`ultima_sessao_concluida\` idênticas e
  \`fechamento_confirmado=true\`; demais exigem
  \`periodo_identificado=true\`. Confrontar \`variacao_pct\` com
  \`valor_anterior\`, quando presente, antes de aprovar.
- Fretes: \`tipo=FRETE_ANUNCIADO\`, município + UF, \`pickup_entity_id\`,
  \`transportadora\`, \`produto\`, \`equipamento\`, \`regime_pf_pj\`,
  \`condicao_pedagio\`, \`valor_rs_t\`, \`referencia_em\`; volume opcional
  \`volume_t_dia\` com \`classificacao_volume\`. O validador não transforma
  anúncio em negociação, transporte realizado nem média municipal.
- A edição original requer estado \`EDICAO_OFFLINE_PREPARADA_SEM_ENVIO\`,
  \`enviado=false\`, data de geração e SHA-256 do texto exato.

### Uso offline (artefatos sintéticos para testes)
\`\`\`sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_editorial_*.py' -v
PYTHONPATH=src python scripts/validar_briefing_offline.py \
  --texto saida/briefing.txt \
  --auditoria saida/briefing.auditoria.json \
  --provas entradas/provas_editoriais.json
\`\`\`
O gerador grava TXT terminado em newline, enquanto o hash se refere ao
conteúdo antes desse terminador. A CLI retira somente esse newline final.
A pasta de provas é um JSON com três arrays \`noticias\`, \`cotacoes\` e
\`fretes\`; falta de dados bloqueia, não cria zero/estimativa fictícia.

## Sequência prevista para homologação E2E
1. **Aquisição autorizada:** conector licenciado, timestamp de publicação
   original, direitos por operação e RAW assinado com SHA/armazenamento.
2. **Normalização:** dados físicos e financeiros, preços por contrato e unidade,
   vigência, calendário do provedor e fonte primária; nunca chamar estimativa
   de observado.
3. **Curadoria:** revisão do fato, deduplicação de evento e licença para resumo.
4. **Renderização NIVON:** resumo sem impactos, último fechamento efetivo,
   notícias da janela móvel, fretes R$/t e t/dia classificados, referências
   portuárias e de insumos quando homologadas.
5. **Gate editorial:** relatório de bloqueios e lacunas, revisão humana
   vinculada ao SHA da edição, trilha de aprovação independente.
6. **Fila idempotente:** somente após aprovação, cada edição/destinatário/
   template deverá ser única em banco durável; reconciliar timeout com prova
   externa, jamais repostar automaticamente.
7. **Envio:** interface com o WhatsApp AI/provedor Meta separada do motor
   editorial, exclusivamente com opt-in, template, canal, custos, webhook
   autenticado e rollback/conciliação homologados.

## Pendências que impedem envio real
- Os manifests e feeds RSS candidatos da PR #8 não foram homologados para
  coleta/armazenamento/publicação; nenhuma fonte pode virar \`APROVADA\`
  por simples configuração local.
- Ainda falta fechar correspondência de calendário do último fechamento
  em CME/ICE/mercado físico, direitos comerciais de redistribuição e
  cobertura de pecuária, diesel, fertilizantes e line-up.
- O pipeline existente não entrega automaticamente o pacote completo de
  evidências exigido pelo novo gate; ligação direta dos coletores e
  persistência bitemporal ainda é etapa de integração.
- CI precisa passar no SHA final da branch e novamente no merge integrado
  com as PRs #8/#13 e demais frentes. Testes sintéticos não homologam RAW real.
- Infraestrutura, agendamento diário com timezone, clock drift, outbox durável,
  backup/restore, Meta Business e templates aprovados não foram verificados.
- Aprovação humana explícita de lançamento é obrigatória. Nenhum envio,
  contratação, ativação de agendamento, merge ou deploy nesta PR.

**Indicadores de aceite da etapa atual:** testes de regressão e revisão de
código; bloqueio determinístico diante de informação ausente ou falsa;
nenhuma operação de rede/WhatsApp; integração E2E real ainda NÃO HOMOLOGADA.


## Continuação autónoma — 20/10/2026: evidências direto do pipeline

**Objetivo executado em código:** não pedir novamente metadados que o NIVON já
conhece após o parse do RSS, a curadoria e a renderização. Nenhuma aprovação
externa é inferida da simples existência do dado.

### Integração implementada
- \`src/nivon/editorial_evidencias_pipeline.py\` compõe
  \`evidencias_editoriais\` usando somente notícias efetivamente selecionadas
  pela mesma política do renderer, SHA-256 real do XML já processado, timestamp
  de coleta informado no manifesto, origem e evidência de política de direitos.
- Indicadores e fretes são encaminhados preservando metadados declarados.
  \`valor_num\` só é aceito como valor numérico estruturado de indicador;
  textos formatados não são transformados em números automaticamente. Sessão
  CME/ICE, natureza, unidade, horário de origem e rastreabilidade continuam
  AUSENTES se os coletores ainda não os fornecem.
- \`pipeline_briefing.gerar_edicao_offline\` retorna
  \`evidencias_editoriais\` + \`preflight_editorial\` com todos os motivos
  de bloqueio. O estado de edição continua
  \`EDICAO_OFFLINE_PREPARADA_SEM_ENVIO\`, independentemente de resultado de
  pré-validação.
- \`scripts/gerar_briefing_offline.py\` já serializa esses campos no arquivo
  \`*.auditoria.json\` existente, sem novo CLI de coleta, fonte de dados ou
  armazenamento de texto de terceiros.
- \`scripts/validar_briefing_offline.py\` agora usa a auditoria existente
  automaticamente, sem \`--provas\`. Quando for necessário complementar
  verificações independentes, \`--provas\` é um arquivo suplementar
  **vinculado ao mesmo SHA da edição**. O módulo
  \`conciliar_complementos\` rejeita alteração de campos imutáveis, aumento de
  número de registros, troca de URL/artigo/hash RSS e substituição de origem.
  Uma nova identidade de evento precisa de \`evidencia_evento_id\`, e
  publicação original verificada requer \`evidencia_publicacao_original_id\`.
  Fechamento confirmado requer \`evidencia_sessao_id\`.
- É intencional que a edição sintética com data de RSS aceita produza
  \`publicacao_original_verificada=false\` e \`evento_id=null\`.
  **Sua pré-validação falha até haver comprovação externa.** Esse é o teste
  funcional de recusa segura, não defeito de disponibilidade.

Exemplo com o mesmo TXT e auditoria de uma geração offline:
\`\`\`sh
PYTHONPATH=src python scripts/validar_briefing_offline.py \
  --texto saida/briefing.txt \
  --auditoria saida/briefing.auditoria.json
\`\`\`

Complemento externo opcional (sem direito a alterar fatos conhecidos):
\`\`\`sh
PYTHONPATH=src python scripts/validar_briefing_offline.py \
  --texto saida/briefing.txt \
  --auditoria saida/briefing.auditoria.json \
  --provas entradas/complementos_independentes.json
\`\`\`

O JSON de complemento deve conter \`sha256_edicao\` e três listas alinhadas,
\`noticias\`, \`cotacoes\`, \`fretes\`, com campos adicionais permitidos somente
para o mesmo registro; sua validade legal/técnica continua sujeita a
verificação humana e às evidências de origem. Nunca declarar licença válida a
partir de um documento sem direitos efetivamente revisados.

### Testes e evidências
- Integração, hash real do feed sintético, coleta original, pacote em JSON,
  CLI sem \`--provas\`, bloqueio automático, preservação da proveniência,
  identidade de acontecimento, impossibilidade de injetar artigo extra e
  dependência de prova documental: \`tests/test_editorial_pipeline_integrado.py\`.
- Commit testado: \`aad0354a57e991ceb886619fe8aa01bad973d0ee\`.
- Execução: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39488632735
- **1.049 testes aprovados, zero falhas**, na suíte do job principal.
  Testes usam fixtures; nenhuma coleta real, serviço externo ou canal Meta
  foram ativados.

### Próximas tarefas (priorizadas)
1. Associar nativamente a cada indicador publicado a fonte, \`valor_num\`,
   unidade, natureza, referência/competência, publicação/coleta, SHA do RAW,
   licença e calendário de fechamento homologado; reconciliar com todos os
   campos renderizados (incluindo fretes de mesmo corredor e transportadoras).
2. Vincular \`evento_id\` e documento de decisão editorial à curadoria
   antes da deduplicação e comprovar publicação original por fonte.
3. Reconciliar PR #26 com PR #13 e demais branches para evitar regressões de
   timezone, corte de preços e rotas, sob auditoria independente.
4. Preparar scheduler diário e ledger de idempotência **desativados**,
   reserva persistente, backup/restore e integração WhatsApp AI somente
   após direitos comerciais, opt-in e aprovação de custos/canal.
5. Cobertura adicional de ICE, CBOT, mercado físico, fertilizantes e line-up
   nacional depende de dados homologados; não simular disponibilidade.

**Estado operacional mantido:** código offline e CI aprovados em revisão;
sem deploy, merge, assinatura paga, ativação de fonte ou envios.


## Integração incremental: PTAX → evidência financeira (20/10/2026)

O conector offline \`ptax_briefing.construir_indicador_ptax\` já verificava
SHA do JSON original, tipo de boletim \`Fechamento\`, moedas USD/EUR,
competência e cotação de venda. Nesta rodada ele também entrega ao motor
editorial \`valor_num\`, \`grupo=CAMBIO\`, \`unidade=R$/USD\` ou
\`R$/EUR\`, natureza, competência, horário de coleta preservado, SHA original
do snapshot e documento de direitos declarado pela fonte. O renderer
preserva quatro casas decimais e explicita a unidade.

**Limite explícito:** \`Fechamento\` na resposta OData não prova que essa
é a última sessão concluída nem fornece o horário externo de publicação.
Por isso \`ultima_sessao_concluida=None\`,
\`fechamento_confirmado=False\` e \`publicado_em=None\` permanecem
sem preenchimento positivo. O preflight bloqueia esse candidato até a
homologação do calendário, edição e direitos da fonte. Não houve consulta
real a BCB, ativação de rota, alteração de licença ou disponibilização
de preços em produção.

Regressões acrescentadas a \`tests/test_pipeline_ptax_briefing.py\`
conferem os campos oriundos do snapshot de teste, proibição de marcar
última sessão automaticamente e bloqueio por falta de prova independente.
