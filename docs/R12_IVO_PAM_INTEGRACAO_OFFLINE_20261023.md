# NIVON — R12 | Consolidação do IVO/PAM em lote técnico separado

**Data:** 23/10/2026. **PR de integração:** #194 draft, base PR #192.

## Integração real de código

- Fonte: PR #7 IVO PAM, delta entre commits `2737e2e527dcb5a03653f0391a8661c6790dfe0e` e `06afe50b1a310a6ddd58c233fba6002f3a715556`.
- Foram copiados **33 caminhos por blobs SHA originais**, mantendo os arquivos anteriores que não tiveram alteração independente. O diff foi verificado: os quatro arquivos pré-existentes modificados permaneceram idênticos ao baseline da PR #7 antes da substituição.
- As famílias incorporadas são: normalização e semântica de dados SIDRA/PAM, planos e erratas, histórico de vintages e capturas, quarentena, qualidade, pacote de auditoria, operação pontual, recuperação/backup e teste de armazenamento GCS com transporte sintético, configurações e documentação.
- **Excluídos:** `.github/workflows/ivo-pam-piloto.yml` — contém schedule, OIDC de escrita e integração cloud — e `tests/test_ivo_pam_workflow_gcs.py`, que requer esse workflow em seu caminho executável. Nenhum agendamento foi criado ou habilitado nesta PR.
- A presença do adaptador `ivo_pam_storage_gcs.py` no código **não autoriza seu uso real** nem comprova egress seguro, licença de dados, gasto ou restauração de bucket. Não foram fornecidas credenciais nem invocadas operações HTTP nesta integração.
- Documentos originais do PR #7 são registros de outra frente. Referências a coleta real, execução anterior e publicações não são atestadas novamente por esta integração e NÃO são dados atuais da base operacional.

## Evidências técnicas

- A primeira integração passou no [CI do núcleo #39984909434](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984909434): **2.242 testes, 0 falhas, 3 ignorados**.
- O segundo [CI de acessos #39984909385](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984909385): **2.242 testes, 0 falhas, 35 ignorados**. USDA/ANA/INMET permaneceram `REDE_DESATIVADA`.
- Entre as regressões de alto valor: revisão de PAM anual mantém duas versões da mesma safra e restauração em novo ciclo; ZIP com objeto adulterado é recusado antes de promover estado; a quarentena mantém separação entre dados observados, pendentes e inferidos. Tudo em testes locais.
- **Ainda não houve** teste com banco em GCP, persistência BigQuery, promoção à Knowledge Factory ou prova de licença de coleta corrente.

## Pendências e próximo lote

1. Confirmar semântica de cada variável PAM/ano/produto, temporalidade da publicação, revisões e cobertura dos municípios, sempre distinguindo valores reais observados de fixtures e projeções.
2. Testar isolamento, assinatura de proveniência e restauração completa no Segundo Cérebro sem promover automaticamente registros IVO a conhecimento canônico.
3. Auditar permissões, budget e saída HTTP em nível de rede antes de avaliar cliente GCS e workflow PAM live; não inserir jobs com cron em uma integração de testes.
4. Reconciliar a PR #7 novamente caso seu HEAD avance; não assumir que os 33 arquivos importados incluem alterações posteriores a `06afe50b...`.
5. A PR #194 segue draft e precisa de avaliação independente antes de merge, agendamento, publicação, coleta, uso de credenciais ou despesas.
