# Hospedagem única no Google Cloud

O destino do NIVON é o Cloud Run privado já previsto no repositório. A #286
remove os dois `vercel.json` sem apagar `public/`, `apps/nivon-terminal/` ou
`api/mercado.js`. Não cria servidor, projeto, pipeline ou coletor adicional.
Recursos externos e domínios legados não são alterados. Referências em documentos
históricos registram decisões antigas, não opções ativas de hospedagem.

## Servidor e build existentes

O ponto de execução é `src/nivon/terminal_web.py`, com a interface ferroviária
existente, `/healthz` e `/api/v1/ferrovia`. A imagem existente é
`infra/google_cloud/Dockerfile.terminal`; o build é
`infra/google_cloud/cloudbuild.terminal.yaml`. O fluxo de publicação permanece
`scripts/deploy_terminal_privado.sh`, exclusivamente mediante aprovação específica.
Não adicionar outro servidor para hospedar o portal estático.

Para validar localmente, da raiz do checkout com o pacote instalado:

```sh
node --check public/assets/nivon.js
node --test tests/terminal_publico.test.js tests_web/mercado_portal.test.cjs
python -B -m unittest discover -s tests -p 'test_terminal_publico.py' -v
python -B -m unittest discover -s tests -p 'test_terminal_web.py' -v
python -B -m unittest discover -s tests -p 'test_terminal_go_live_policy.py' -v
NIVON_BQ_PROJECT=nivon-data NIVON_BQ_DATASET=nivon_raw PORT=8082 python -m nivon.terminal_web
```

Validar internamente `/healthz` (200, `PROCESSO_ATIVO`) e `/` (200, `NIVON`).
A rota ferroviária requer autenticação Google e BigQuery; os testes exercitam
seu contrato HTTP com fixtures sintéticas e cliente injetado. Não consultar
serviços reais sem os gates de leitura/custo aplicáveis. Health não prova fonte.

## Preservação da interface

Os headers antes declarados no host removido foram preservados em
`infra/google_cloud/portal-security-headers.json` e
`apps/nivon-terminal/security-headers.json` como contratos de referência para
consolidação na #287. **Esses JSON não são configuração carregada pelo servidor
Python atual.** O servidor existente continua aplicando seus próprios headers.
A referência do portal permite `connect-src 'self'` para a API de mesmo domínio.
A API BCB e seus testes continuam preservados; isso não a torna publicada no
servidor ferroviário nem prova atualização do BigQuery.

A #287 deve integrar a experiência preservada ao servidor existente, avaliando a
PR #276 e sem ativar um segundo terminal. A #286 não afirma essa integração.

## Gate de publicação

Nenhum deploy ou alteração de IAM é feito neste bloco. O terminal depende do
controle de invocação do Cloud Run para acesso privado; não implementa login.
Não expor diretamente à Internet e não habilitar invocação anônima. A publicação
exige aprovação específica de custo/deploy e evidências da #281.

Variáveis e gates existentes: `NIVON_TERMINAL_ARTIFACT_REPO`,
`NIVON_TERMINAL_EXECUTION_SA`, `NIVON_GCP_COST_REVIEWED` e
`NIVON_GO_LIVE_DEPLOY_APPROVED`. Não definir os gates como verdadeiros por conta
própria. Build, CI e smoke local não são homologação nem go-live.
