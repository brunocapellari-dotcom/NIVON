# NIVON — primeiro terminal web real (versão interna)

Implantação sobre o projeto Vercel existente `nivon`, sem novo provedor pago, sem framework, tokens ou bancos paralelos.

## Já disponível no código
- `index.html`: interface responsiva, navegação funcional, painéis de mercado e fontes, estados explícitos e botão de recarregar.
- `api/mercado.js`: endpoint somente leitura, HTTPS fixo do BCB, códigos SGS **1** (dólar venda, BRL/USD) e **11** (Selic efetiva, % ao dia).
- Cada série traz valor oficial, data de referência, idade e `SOURCE_LAG` quando defasada. Falhas mantêm o valor **ausente**, nunca zero ou valor fictício.
- `vercel.json`: configuração de função serverless e proteção HTTP; no projeto Vercel existente manter **SSO habilitado**.
- `tests_web/mercado.test.cjs`: sem mocks de preços na interface, validação de tipos, datas, erros HTTP e ausência de URLs controláveis pelo usuário.
- Nenhuma integração afirmada com BigQuery: rota pública de leitura direta usada **somente nesta primeira versão interna**. O pipeline canônico GCS/BigQuery continua sendo a fonte de verdade para módulos agrícolas, fretes, ferrovias e marítimo.

## Evidência que falta para go-live interno
1. CI `NIVON - Web MVP E2E publico sem credenciais` verde no GitHub.
2. Vercel production deployment do commit que contém `index.html`, `api/mercado.js` e `vercel.json` com estado `READY`.
3. Verificar autenticação SSO (não removê-la automaticamente), HTTP 200 após login em `/` e `/api/mercado`; usar navegação móvel e desktop.
4. Verificar na resposta duas fontes oficiais e datas recentes. Se o BCB bloquear, o terminal mostra falha, **não** chama painel "atualizado".
5. Go-live pleno do NIVON ainda requer criar tabelas `nivon_observacoes` e `agro_publicacoes_staging` no Google Cloud, executar cargas reais com aprovações de IAM/custos e integrar resultados na interface, sem expor credenciais.

## Ambiente conhecido (inspeção anterior)
- Projeto Vercel: `nivon`; domínio atribuído `nivon-bcfc2.vercel.app` e aliases; deployment antigo `READY` não prova conteúdo entregue.
- SSO ativo na configuração existente; permanecer ativo até revisão de acesso público.
- Google Cloud: `nivon-data`, bucket `nivon-data-raw-2026`, dataset `nivon_raw`. Em auditoria read-only, tabelas agrícolas **AUSENTES**; nenhuma flag de custo/IAM foi ativada por este patch.

**Não confundir versão interna parcial com conclusão do Bloomberg do Agro ou divulgação pública comercial.**
