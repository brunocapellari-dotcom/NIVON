# NIVON — Trava de segurança dos diagnósticos de fontes em GitHub Actions

**Revisão:** 20/10/2026. **Estado:** alteração proposta na PR #10, sem merge ou execução de fonte real.

## Falha identificada

O workflow `.github/workflows/testes.yml` permitia que quem pudesse executar
`workflow_dispatch` invocasse diagnósticos com acesso a fontes oficiais reais.
O acionamento ser manual não demonstrava aceite de direitos, escopo de
coleta, privacidade, custos ou disponibilização comercial.

## Política fail-closed aplicada

A suíte sintética `validar-nucleo` permanece disponível em `pull_request`.
Os cinco jobs de diagnóstico REAL requerem simultaneamente:

1. `workflow_dispatch` manual na branch `main` (não em PRs);
2. input booleano `confirmar_diagnostico_fonte_real=true` — padrão **false**;
3. uma variável própria da fonte, com valor **exatamente** `true`.

| Job de diagnóstico | Variável de repositório exigida |
|---|---|
| conferir-schema-mapa | `NIVON_FONTE_MAPA_SIPEAGRO_HOMOLOGADA` |
| inspecao-conab-xls | `NIVON_FONTE_CONAB_XLS_HOMOLOGADA` |
| inspecao-antt-ferrovias | `NIVON_FONTE_ANTT_FERROVIAS_HOMOLOGADA` |
| inspecao-antt-csv-2026 | `NIVON_FONTE_ANTT_CSV_HOMOLOGADA` |
| inspecao-anp-diesel | `NIVON_FONTE_ANP_DIESEL_HOMOLOGADA` |

**Nenhuma dessas variáveis foi criada/alterada nesta entrega.**
Variável ausente ou com valor diferente de `true` bloqueia o job.

As variáveis são uma trava operacional adicional, **não prova de licença**:
a autorização específica, duração, direitos de coleta/armazenamento,
reutilização, custos, consentimento e registro de evidência precisam existir
antes de qualquer habilitação. Executar em `main` não significa que haja
autorização geral de produção; os diagnósticos não implantam serviços.

## Verificação automatizada

`tests/test_infra_ci_source_gates.py`, executado na suíte padrão sem
dependências extras, verifica:
- evento não privilegiado, permissão `contents: read`, ausência de agenda;
- confirmação manual obrigatória com `default: false`;
- gates distintos para cada fonte, vinculados a `main`;
- ações externas fixadas por commit SHA de 40 caracteres;
- checkout sem persistência de credenciais.

`PYTHONPATH=src python -m unittest tests.test_infra_ci_source_gates -v`
(ou `PYTHONPATH=src python -m unittest discover -s tests -v`).

## Limites desta correção

Este teste é estático e confere invariantes do YAML: não é um parser YAML
completo, scanner de segredos, verificação de CVE ou simulação do executor
GitHub Actions. A segurança final exige revisão de código, execução do CI
no commit exato, validação de direitos por fonte e auditoria independente.

Nenhuma VM, banco, secret, agendamento recorrente, deploy, dados ou envio
WhatsApp é criado aqui.
