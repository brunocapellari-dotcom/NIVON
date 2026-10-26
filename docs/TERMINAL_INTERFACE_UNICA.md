# Interface privada única (#287)

O servidor e a imagem continuam sendo `nivon.terminal_web` e
`infra/google_cloud/Dockerfile.terminal`. A raiz `/` agora reutiliza a estrutura
visual e o CSS da PR #276 (ref inspecionada
`38d6d577832677c69eca3aa10da62d6ee34c1238`), adaptados à API ferroviária já
existente. Não importa `portal_interno.py`, seu servidor WSGI, snapshot externo,
workflow GCS ou agendamento. Não cria outro leitor, processo ou frontend ativo.

Os assets residem em `src/nivon/portal_static/` e são incluídos no pacote Python.
`public/` e `apps/nivon-terminal/` são preservados como legado para consulta;
não são servidos nem implantados como produtos paralelos. A retirada de suas
configurações de hospedagem é entregue separadamente na branch da #286.

## Fluxo ponta a ponta

`GET /` → assets locais permitidos → `GET /api/v1/ferrovia` → cache existente →
leitor BigQuery existente. O navegador não recebe SQL, credenciais ou endpoint
BigQuery. Mercado, marítimo e clima permanecem explicitamente indisponíveis,
sem cotação presumida ou número zero fabricado.

API/UI mostram competência e coleta separadas, SHA-256 anual e alerta de
defasagem da #289. O botão atualiza a visualização respeitando cache de 15 min;
não promete nova coleta. Falha limpa dados visíveis da leitura anterior.

HTML/JS/CSS são servidos pelo mesmo handler com allowlist de rotas,
`Cache-Control: no-store`, CSP sem `unsafe-inline`, noindex e proteção contra
iframe. A autenticação continua no IAM do Cloud Run: esses headers e o bind
local não implementam login nem substituem controle de invocação.

## Verificação reproduzível

```sh
python -B -m unittest discover -s tests -p 'test_terminal_web.py' -v
node --check src/nivon/portal_static/portal.js
node --test tests_web/terminal_ferrovia_ui.test.cjs
python -m pip wheel --no-deps --wheel-dir /tmp/nivon-wheels .
```

Os testes HTTP usam cliente/consulta sintéticos injetados e verificam raiz,
assets, API e erros. Os testes Node executam o JS real com DOM/fetch simulados;
não são um navegador completo nem prova de acesso GCP. A sessão validou também
os assets e as rotas a partir de um wheel instalado fora do checkout.

Não há deploy, IAM, novo custo ou homologação LIVE neste bloco. A branch depende
da #289 e deve ser revisada em relação a ela; não mesclar automaticamente.
