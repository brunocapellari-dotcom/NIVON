# NIVON — Integração de código das PRs #8, #13 e #26

Data: 21/10/2026. Status: **integração em draft, apenas offline**.

## Origem e resolução manual de conflito

- Pai editorial PR #26: `3beda393992460b7c56d501746cd6e78e075401a`.
- Pai de coletores PR #8: `79423add99a5b92186839d969f52d1eadf2f7501`.
- Pai de integração/auditoria PR #13: `9f1a5e0ded09ac2246cc83b764ddb60f44436986`.

Esta composição usa um commit com três pais, árvore baseada no HEAD da
PR #26 e aplicação explícita do delta mais recente de #8 e dos artefatos
compatíveis de #13. Não é uma mesclagem automática que aceite qualquer
resolução implícita.

**Conflito resolvido:** em `src/nivon/briefing_composto.py`, prevalece
o contrato de **frete individual** da PR #26; as dez janelas de frescor da
PR #13 já foram integradas na PR #26 pelo módulo
`src/nivon/politica_frescor_briefing.py` e compartilhadas com
`editorial_preflight.py`. Não substituir o renderer pelo código antigo
da PR #13, que só incluía corredor, preço e horário.

Os testes de regressão da PR #13 são trazidos com fixture de frete
atualizada para o novo contrato de identificador, estabelecimento,
transportadora, produto, equipamento, regime PF/PJ e pedágio.
A documentação de governança da PR #13 é arquivada como referência
histórica, não como status atual das branches.

## Coleta ANP da PR #8 (sem ativação)

O delta `8f3ff501...79423add...` consiste em mudanças no cadastro
`config/rotas_coleta.v1.json`, `src/nivon/anp_monitor_atualizacao.py`,
`scripts/auditar_atualizacao_anp.py`, documentação e testes do
monitoramento **offline** do índice de publicações ANP. São importados
como arquivos/objetos da PR #8, sem reimplementar o monitor.

O monitor não baixa automaticamente preço nem XLSX, não reconhece
licença comercial por inferência e sempre entrega
`publicacao_autorizada=false` e `coleta_preco_executada=false`.
Dados do índice não são substitutos dos registros ANP com semana,
posto, município, produto, SHA do RAW e direitos auditados.

## Condições de aceite

1. Testar a integração no **mesmo SHA da árvore mesclada**, verificando
   todos os testes da suite em GitHub Actions.
2. Reprovar cadastro de fonte incorreto, índice sem dados, dados
   sintéticos tratados como cotações reais e mudança de contrato de
   frete/último pregão.
3. Inspeções reais permanecem manuais e `skipped` em PRs.
4. PR em draft; **não** fazer merge na main, deploy, cron, integração
   de canal Meta/WhatsApp AI ou enviar mensagens.
5. Auditoria técnica independente e revisão dos direitos da fonte são
   pré-requisitos de homologação, não consequências da CI verde.

**Próxima ação:** confirmar comparações ancestrais e PR de integração,
executar testes, corrigir regressões e entregar o SHA de integração
à Direção Técnica para auditoria e eventual promoção controlada.
