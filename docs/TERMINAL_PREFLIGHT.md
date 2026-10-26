# Pré-voo privado do terminal (#288)

Da raiz do checkout com o pacote instalado:

```sh
python -B -m nivon.terminal_preflight
```

Emite um JSON e sai com código 2 enquanto houver gates ou evidências ausentes.
Não consulta a rede por padrão. Reutiliza projeto/dataset do terminal existente,
região e verificações de metadados do script de deploy; não executa esse script.

Variáveis existentes: `NIVON_PROJETO=nivon-data`, `NIVON_DATASET=nivon_raw`,
`NIVON_TERMINAL_ARTIFACT_REPO`, `NIVON_TERMINAL_EXECUTION_SA`,
`NIVON_GCP_COST_REVIEWED`, `NIVON_GO_LIVE_DEPLOY_APPROVED`.
O diagnóstico acrescenta `NIVON_TERMINAL_IAM_REVIEWED`: confirmação humana de
revisão do IAM efetivo da identidade de execução e do executor de deploy,
incluindo herança e permissões da view. Não definir gates como `true` para
contornar pendências. Esse novo gate é do diagnóstico; não altera o deploy atual.

Após aprovação dos gates, `--executar` consulta exclusivamente metadados, usando
gcloud autenticado e o SDK `nivon[gcp]`: repo Docker, service account, billing,
dataset/view e serviço existente, políticas de projeto e serviço, identidade de
execução, label de titularidade e verificação IAM de invocação habilitada.
Se não houver serviço existente, a prontidão permanece bloqueada: não cria outro.

Não executa SQL, build, deploy, concessão IAM, leitura de valores de secrets ou
teste de permissão de escrita. `ready_for_deploy` exige todos os checks e os
gates humanos, mas não prova IAM efetivo, custo zero, CI remoto ou go-live.
Herança de pasta/organização exige revisão humana: políticas de projeto e serviço
isoladas não comprovam todo o grafo de autorização. `allUsers` e
`allAuthenticatedUsers` observados impedem prontidão.

Erros externos são sanitizados. Sem acesso não significa recurso ausente: ambos
ficam bloqueados, sem inferência de que se deve criar um recurso. JSON bruto de
IAM, nomes de contas, tokens, stderr e valores do ambiente não são emitidos.

CI usa apenas doubles e não autentica Google nem cria jobs faturáveis. Sucesso
simulado fica explicitamente separado de funcionamento real.
