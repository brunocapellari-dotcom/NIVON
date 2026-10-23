# IVO — Rodada 17: continuidade do acervo PAM no Google Cloud Storage

**Data:** 23/10/2026. **Branch:** `feat/ivo-governed-learning-20261019`,
PR #7 (draft). **Não houve merge, deploy, criação de bucket,
habilitação de API/cobrança ou gravação REAL no GCS nesta rodada**.

## Decisão de engenharia e prioridades executadas

O IVO já demonstrou a cadeia PAM/SIDRA com **24 capturas reais,
6 arquivos/vintages distintos** e backups externos pontuais no Drive.
Faltava um protocolo de persistência e recuperação **automático** entre
runners efêmeros sem depender da expiração de artifacts do GitHub.

| Prioridade | Entrega | Evidência/estado |
|---|---|---|
| 1 | Cliente GCS de leitura e escrita sob identidade temporária | **Implementado** na biblioteca padrão, sem token em arquivo |
| 2 | Backup imutável por conteúdo e hash | **Implementado**, `ifGenerationMatch=0` e readback integral |
| 3 | Último estado com proteção de concorrência | **Implementado**, ponteiro condicional por `generation` |
| 4 | Recuperação com auditoria completa antes de usar | **Implementado**, SQLite + objetos originais + recibos |
| 5 | Garantir nenhuma reescrita da história | **Implementado**, compara todas as linhas antigas de versões e capturas |
| 6 | Pipeline GitHub Actions com Workload Identity Federation | **Integrado e guardado**, sem credenciais reais configuradas |
| 7 | E2E de dois backups, recuperação, falhas/corrupção | **Testado com simulador de API GCS e SQLite reais** |
| 8 | GCS real e agendamento operacional | **Não executado**, depende da infraestrutura IAM/bucket já aprovada |
| 9 | Backtest as-of PAM | **Não executado**, falta versão original pré-errata |

## Código

`src/nivon/ivo_pam_storage_gcs.py` implementa a API JSON oficial do
Google Cloud Storage **sem dependência adicional**: TLS/HTTPS, sem
proxy/redirecionamento, bucket e objetos restritos ao namespace
`nivon/ivo/pam/v1`, token OAuth temporário em
`NIVON_GCS_ACCESS_TOKEN` (não passado na linha de comando), limite
de 128 MiB por operação e dois modos:

- **Recuperar:** ler o `controle/ultimo.json`, capturar a
  `generation` precisa, baixar o ZIP imutável apontado, conferir
  SHA-256 completo, restaurar em diretório temporário **novo**,
  executar auditoria SQLite ↔ JSON ↔ recibos e só depois publicar
  o backup local. Se ponteiro ou objeto estiver ausente/corrompido,
  **falha sem reiniciar o histórico**.
- **Publicar:** auditar ZIP local; comparar backup anterior remoto e
  todas as linhas históricas (versões e capturas), exigindo acréscimo
  sem sobrescrever registros antigos; subir objeto pelo SHA com
  `ifGenerationMatch=0`; baixar novamente o objeto e verificar
  seu SHA e estrutura; atualizar `ultimo.json` por
  `ifGenerationMatch=<generation anterior>`. Concorrência resulta
  em falha 412, nunca *last writer wins*. Verifica ponteiro após
  a atualização.

Comandos para CI:

```bash
# Somente em runner COM OAuth access token temporário provisionado.
PYTHONPATH=src python -m nivon.ivo_pam_storage_gcs estado --bucket "$NIVON_PAM_GCS_BUCKET"

PYTHONPATH=src python -m nivon.ivo_pam_storage_gcs recuperar \
  --bucket "$NIVON_PAM_GCS_BUCKET" --arquivo anterior.zip

PYTHONPATH=src python -m nivon.ivo_pam_storage_gcs upload \
  --bucket "$NIVON_PAM_GCS_BUCKET" --arquivo ciclo/estado_pam.zip
```

O primeiro upload de bucket ainda vazio requer `--bootstrap` e
uma semente real do histórico. Não importa como normal uma
inicialização silenciosa a partir de zero.

## GitHub Actions

`.github/workflows/ivo-pam-piloto.yml` recebeu uma integração GCS
**opt-in**, somente quando *ao mesmo tempo* houver:

- Evento no `refs/heads/main` (nunca execução de credenciais GCS em PR draft);
- Variável `NIVON_PAM_GCS_BUCKET` apontando para bucket existente;
- Variável `NIVON_GCP_WIF_PROVIDER` com Workload Identity Pool/Provider;
- Variável `NIVON_GCP_SERVICE_ACCOUNT` com conta de serviço autorizada.

Com essas configurações, o job usa
`google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093`
(tag oficial v3 da data) com `token_format: access_token` e
`id-token: write`, sem exportar JSON key.
**A rotina agendada é ignorada no nível do job se não houver as três
variáveis**, portanto não consome minutos de runner nessas condições.

No primeiro bootstrap, variável opcional
`NIVON_PAM_GCS_BOOTSTRAP=true` permite recuperar a
semente auditada **de 24 capturas** do run `39946796466` (apenas
enquanto seu artifact estiver disponível); não cair na versão
anterior de 6 capturas. Depois do primeiro backup GCS, o próprio
Google Cloud torna-se referência para recuperar o estado. Se o
bucket já contém ponteiro, qualquer erro de acesso a ele BLOQUEIA
a coleta, sem fallback para ZIP mais antigo.

O job de coleta real só usa o GCS se as condições acima estiverem
configuradas. No PR draft, executa somente teste offline e não
faz gravações no GCS. Não há segredo de serviço no repositório.

**Importante IAM:** segundo a API oficial do Google Cloud,
ler objetos exige `storage.objects.get`; criar um novo exige
`storage.objects.create`; substituir `ultimo.json` exige
também `storage.objects.delete`. Conceder o menor escopo possível
ao bucket/namespace do NIVON, com política federada restrita à
identidade do repositório e branch principal. Não conceder direitos
sobre outros buckets por padrão. Fonte:
<https://cloud.google.com/storage/docs/json_api/v1/objects/insert>
e <https://cloud.google.com/storage/docs/request-preconditions>.

## Testes e limites

`tests/test_ivo_pam_storage_gcs_e2e.py` usa um servidor GCS
**inteiramente simulado em memória**, mas dados SQLite/quarentena/ZIP
**reais na execução do runner**. Verifica:
1. bootstrap e publicação inicial;
2. recuperação, revisão anual e segunda publicação;
3. falta de estado e exigência explícita de bootstrap;
4. rollback de backup antigo;
5. corrida de `generation` e falha segura;
6. readback adulterado antes de atualizar o ponteiro;
7. objeto remoto corrompido na recuperação;
8. tentativa de sobrescrita de arquivo local;
9. bucket/token/objeto fora do contrato;
10. reescrita de metadados históricos com todas as chaves intactas.

`tests/test_ivo_pam_workflow_gcs.py` confere gatilhos, identidade
federada, ordem de recuperação/coleta/auditoria/upload,
pré-condições do bootstrap, bloqueio de backup e ausência de
execução automática de rede no PR.

**Não houve upload ou download GCS real nesta rodada.** Testes do
simulador provam o protocolo lógico; não substituem testes com IAM,
bucket e a API remota real. O Google Drive já contém uma cópia
pontual verificada do [acervo com 24 capturas](https://drive.google.com/file/d/1cDbsBRI5aQFeanKlkcoNmPxYx--vqCEc/view?usp=drivesdk);
a automação de backup externa no GCS só funcionará com as variáveis
e o bucket efetivamente provisionados. Nenhum custo foi autorizado.

## Próximas ações sem repetição de trabalho

1. Confirmar se já existem bucket GCS, Workload Identity Provider e
   Service Account do NIVON, e registrar as três *repository variables*.
   Sem acesso a configurações administrativas do GCP/repo, isso é
   um bloqueio de implantação; **não criar bucket pago**.
2. Disparar uma execução real sob WIF com acesso temporário e
   verificar readback/GCS, histórico acumulado e restauração.
3. Garantir que o backend tenha alerta de mudança de SHA e que a
   retenção do bucket e custos do storage estejam controlados.
4. Integrar os resultados anuais ao painel analítico/segundo cérebro
   como estatísticas PAM com captura bitemporal, sem transformar
   captura de 2026 em publicação histórica de 2021.
