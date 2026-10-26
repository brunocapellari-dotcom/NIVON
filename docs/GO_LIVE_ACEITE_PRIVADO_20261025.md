# NIVON — critério automático do primeiro go-live privado

A entrega mínima continua sendo **o terminal existente** na main, sem segundo frontend:
Cloud Run `nivon-terminal` na região `southamerica-east1`, com BigQuery
`nivon-data.nivon_raw.vw_antt_ferrovia_od_atual`.

Este incremento evita confundir `gcloud run deploy` bem-sucedido com serviço
de fato acessível. Após o deploy **manual e explicitamente aprovado**,
`src/nivon/terminal_live_acceptance.py` inspeciona os metadados Cloud Run e
a política IAM por consultas de leitura. Recusa invocação pública, nomes,
região, rótulos, conta de execução ou estado Ready incompatíveis.

A identidade temporária obtém um ID token em memória para a URL legítima do
serviço, sem salvá-lo em logs. Faz três GET HTTPS autenticados: `/healthz`,
`/` e `/api/v1/ferrovia`. Confere a interface, a natureza observada
declarada dos dados ANTT, a sequência anual, somas consistentes,
competência não futura e o limite de 250 MB faturáveis por consulta.
Erros não exibem tokens, SQL, URL privada ou corpos de dados.

**Bloqueios reais identificados em 25/10/2026:** na execução
[40261018737](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40261018737)
a federação WIF executou o diagnóstico, mas as variáveis
`NIVON_TERMINAL_ARTIFACT_REPO` e `NIVON_TERMINAL_EXECUTION_SA`
estavam vazias. O job de deploy foi corretamente SKIPPED.
A etapa `diagnostico-metadados` na main agora lista em seu Job Summary
candidatos existentes se a conta tiver permissões de leitura. Eles
precisam ser revisados; **não criar ou atribuir papéis automaticamente**.

Após confirmação de IAM, custo e recursos existentes, o proprietário poderá
executar `NIVON - Terminal privado Go Live` manualmente com
`confirmar_deploy=true` e variáveis `NIVON_GO_LIVE_DEPLOY_APPROVED=true`
e `NIVON_GCP_COST_REVIEWED=true`. Sem ambas, nenhuma imagem é construída
nem publicada. Para o smoke funcionar, a identidade que executa o workflow
precisa de `roles/run.invoker` para o serviço, sem bindings para
`allUsers` ou `allAuthenticatedUsers`; caso falte a permissão,
a CI deve falhar explicitamente em vez de inventar go-live.

A publicação de relatório privado no GCS **já foi comprovada** pelo
[workflow 40257509093](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257509093).
Isso não é uma URL autenticada operacional e não substitui o teste
do Cloud Run. Mesmo o smoke aprovado não concede direitos de dados de terceiros,
não ativa CEPEA/IMEA/CONAB e não autoriza envio WhatsApp.

**Critério de go-live 0.1:** job de deploy manual aprovado, CI verde no
mesmo SHA, smoke autenticado completo, IAM privado e confirmação de custo
pelo operador. Nenhuma integração Vercel.


## Consolidação com o portal real incorporado na main

A mesma aplicação privada integra `/`, `/portal`, `/healthz`, `/readyz`, `/api/v1/ferrovia` e `/api/v1/painel`. O aceite depois do deploy autorizado exige HTTP autenticado para todas as seis rotas, série ferroviária ANTT/SIADE coerente, snapshot GCS privado SHA-256, pelo menos duas fontes reais e atualização dentro de 24 horas. Falhas de dados ou de IAM impedem classificar o deploy como pronto. Não há segundo frontend, Vercel, IAM público ou liberação de custos automática.
