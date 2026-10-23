# NIVON — Execução integrada em lote (sem dados externos)

**Status:** pipeline sintético executado de ponta a ponta em **AMD64 e ARM64 nativos**; não é serviço em produção.

## Arquitetura implementada

O módulo `src/nivon/infra_offline_pipeline.py` implementa um contrato de transferência em **SQLite + artefatos JSON íntegros** entre dois contêineres Docker da mesma arquitetura:

1. **Alpine mínimo (prepare)** cria três trabalhos `TEST_SYNTHETIC_SERIE_AAA/BBB/CCC` e arquivos de entrada imutáveis, registrando hash SHA-256 e vencimento no ledger.
2. **Debian analítico (process)** utiliza `pandas` e `StatsForecast.Naive` para gerar previsões determinísticas de horizonte 2 sobre oito observações por trabalho. Reservas (leases) exclusivas, hashes e status ficam no SQLite; não há download nem comunicação externa.
3. **Reprocessamento** identifica os mesmos jobs `SUCCEEDED`, retorna `processed=0` e não acrescenta saídas nem ações.
4. **Falha simulada após lease** cria estado `RUNNING` sem saída. A fase `reconcile` com tempo sintético avançado marca `UNCERTAIN`; somente o contrato sintético e uma fase **explicitamente invocada** permitem reencaminhar o job após comprovar ausência de output. Jobs reais não podem utilizar esse caminho.
5. **Alpine (verify/backup)** verifica três jobs, seis artefatos íntegros, saída prevista e conteúdo canônico; cria backup SQLite coerente inclusive para WAL e cópias dos seis arquivos. O manifesto armazena sete digests SHA-256.
6. **Alpine (restore)** checa os sete digests antes da restauração, restaura para **outro diretório privado** sem sobrescrita, verifica integridade SQLite e chaves estrangeiras e revalida os três jobs. Uma nova execução analítica sobre a cópia restaurada também retorna zero novos processamentos.

## Isolamento e limites

O CI `.github/workflows/infra_analytics_experiment.yml` executa a sequência em runners AMD64 e ARM64 usando o mesmo estágio que já constrói, testa e examina a imagem analítica. Não cria workflows redundantes. Os dois contêineres operam com `--network none`, rootfs `--read-only`, `--cap-drop ALL`, UID 65532, limites de CPU/RAM/PIDs, tmpfs restrito e bind mounts de diretórios privados `0700` situados fora do checkout. Todas as flags reais de runtime, fontes, backup externo e publicação estão explicitamente desativadas. Não acessa CEPEA, IMEA, CONAB, OCI, Google Cloud, WhatsApp, credenciais ou dados operacionais.

**Evidência verificada:** [GitHub Actions 39890487285](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890487285), commit `88e6fc343718b0d58a9317de18ac5135fb20c767`, `SUCCESS` em AMD64 e ARM64: `created=3` e segundo `created=0`; `interrupted_after_lease=true`; `expired=1`, `explicit_requeued=1`; `processed=3` e segundo `processed=0`; `verified_jobs=3`; `files=7` no backup; `restored_jobs=3` e validação pós-restore; zero fontes consultadas e zero publicações. Snapshot SQLite da execução gerou o **mesmo SHA-256** em ambas arquiteturas, demonstrando conteúdo determinístico no ensaio.

Também passaram 1.065 testes Python na suíte geral, seis ignorados, sem falhas. O Trivy da imagem analítica Debian ainda mostra **44 HIGH, 0 CRITICAL**; gate de produção bloqueado, sem suppressions. Backup local foi realizado, **não backup remoto criptografado nem recuperação noutra máquina**.

## Do ensaio para a plataforma real

O contrato é propositalmente limitado a três séries sintéticas fixas, não é agendador nem executor genérico. Antes de processar informações reais será necessário criar fluxos de coleta autorizados, interlocks e reconciliação de efeitos externos, idempotência ao nível do negócio, limites de fila, observabilidade, retenção, backups remotos, segurança e implantação aprovada. Este sucesso não significa que haja operação 24/7 ou infraestrutura cloud ativa.
