# NIVON — Conciliação editorial PR #13 e dependência PR #8

Data-base: 21/10/2026. Status: branch editorial isolada, sem merge,
coleta ativa, envio ou homologação real.

## GitHub conferido antes da alteração

| PR | Branch | SHA consultado | Papel |
|---|---|---|---|
| #26 | feat/editorial-preflight-homologacao-20261020 | 15bd85044aa5492bd57dac46ff1fd5f615186698 | Renderer individual de frete, auditoria e pré-publicação |
| #13 | integration/nivon-auditoria-20261020 | 9f1a5e0ded09ac2246cc83b764ddb60f44436986 | Backstop de frescor por seção |
| #8 | feat/consolidar-coleta-portuaria-20261019 | 79423add99a5b92186839d969f52d1eadf2f7501 | Base RSS, ANP, PTAX e monitor offline |

A PR #26 mantém a base antiga de PR #8 no SHA
\`8f3ff5013e9dc25ce4c8bbbc680e145529de37e8\`. O comparativo oficial
até \`79423add...\` registrou +7 commits, sem alterações dos arquivos
\`briefing_composto.py\`, \`editorial_preflight.py\` ou
\`politica_frescor_briefing.py\` na PR #8.

## Conteúdo da PR #13 conciliado em código

O renderer passa a aplicar os limites de antiguidade máximos da PR #13,
sem modificá-los, pelo módulo único
\`src/nivon/politica_frescor_briefing.py\`:

| Seção | Backstop máximo |
|---|---|
| BOLSAS | 96 horas |
| CAMBIO | 96 horas |
| PRECOS | 7 dias |
| SAFRA | 45 dias |
| PORTOS | 48 horas |
| DIESEL | 16 dias |
| FERTILIZANTES | 45 dias |
| CLIMA | 48 horas |
| LOGISTICA | 72 horas |
| GEOPOLITICA | 72 horas |

Observações obrigatórias:

1. São limites *máximos*, não prova de atualização. Dado recente não
   implica último fechamento, nem sessão oficialmente concluída.
2. A janela de **notícias** permanece separada: publicação original
   independentemente verificada nas últimas 24 horas da geração.
3. Fuso e referência devem ser explícitos. A lógica usa diferença de
   instantes em UTC; o calendário de pregão/competência local exige
   prova da fonte e continua sob controle separado.
4. \`briefing_composto.montar_briefing\` rejeita do texto indicador
   vencido, mesmo que a política de direitos esteja declarada aprovada.
5. \`editorial_evidencias_pipeline.montar_candidatos_evidencias\`
   preserva \`secao\` imutável por indicador. Sem seção, o preflight usa
   mapeamento controlado por grupo: CHICAGO/ICE=BOLSAS, CAMBIO=CAMBIO,
   MERCADO_FISICO/PECUARIA/ENERGIA=PRECOS.
6. O diesel ANP carrega obrigatoriamente \`secao=DIESEL\` e
   \`grupo=ENERGIA\`, com classificação amostral declarada; não pode
   ser reetiquetado como \`PRECOS\` para escapar da política.
7. Os filtros do renderer não garantem que uma edição pode ser enviada.
   A auditoria agrega bloqueios para todos os registros informados e
   depende de direitos, RAW, data original e calendário comprovados.

### Regressões introduzidas

\`tests/test_frescor_briefing_integracao.py\` cobre:
- equivalência exata das dez janelas com PR #13;
- indicador CBOT de 90 dias, dado portuário de 2025, diesel de 17 dias;
- janela de 96 horas no limite e um segundo fora;
- horário futuro ou sem fuso;
- cotação com licença declarada e sessão antiga;
- dado recente sem comprovação de último fechamento;
- indicador de diesel com período de 9 dias dentro da janela de 16 dias,
  sem impor indevidamente a janela de 7 dias de preços físicos;
- rejeição da falsa conversão de ANP amostral para preço spot.

### Estado da PR #8 e handoff

Os commits posteriores ao SHA de base editorial adicionaram:
\`src/nivon/anp_monitor_atualizacao.py\`,
\`scripts/auditar_atualizacao_anp.py\`,
testes offline e a documentação
\`docs/ANP_MONITOR_PUBLICACOES_20261020.md\`, além de
\`config/rotas_coleta.v1.json\`.

Esses componentes monitoram **metadados de publicação** do índice da
ANP, não os preços de combustível, a licença de redistribuição nem a
homologação de um XLSX. O monitor declara
\`coleta_preco_executada=false\` e \`publicacao_autorizada=false\`.
Portanto não alimenta automaticamente \`anp_diesel_briefing.py\` com
qualquer valor numérico nem ativa fonte ou download.

**Integração recomendada à Direção Técnica:** incorporar os sete commits
da PR #8 num SHA comum de integração, executar regressões #8/#26
conjuntas, reconciliar o catálogo de rotas uma única vez e garantir
que informações de índice ANP **nunca** sejam promovidas a cotação.
A operação deve ocorrer numa branch de integração sob revisão e não
ser confundida com aprovação para merge/deploy em main.

## Pendências de liberação

- Homologar amostras oficiais da fonte e direitos de uso comercial.
- Calendário de negociação, comprovação externa de último fechamento e
  horário de publicação original das notícias.
- Testar branches integradas em um único SHA, inclusive fontes e schemas.
- Persistência durável, consentimento e interface do WhatsApp AI
  homologados, sem envio automático nesta fase.

Nenhum número sintético é indicador econômico atual. Todas as execuções
de teste usam fixtures e não substituem auditoria independente.
