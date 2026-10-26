# Checkpoint #287 — uma interface, um servidor

Branch `codex/287-single-private-interface`, empilhada sobre #289 (`6068079`).
Base sugerida para PR: `codex/289-antt-reader-contract`, para mostrar só a integração.

Reaproveita HTML/CSS da PR #276 no servidor existente `nivon.terminal_web`,
sem importar WSGI, novo servidor, pipeline, snapshots, agenda ou deploy. Mantém
API/health do terminal; os assets integram o wheel. CSP sem unsafe-inline.
Módulos ainda não homologados ficam explicitamente indisponíveis. Legados
public/apps preservados; retirada de configs entregue isoladamente na #286.

Validação local: 762 testes Python, sem falhas, 2 skips Parquet opcionais;
3 testes JS da interface aprovados; sintaxe JS e diff-check aprovados.
Wheel produzido, instalado em /tmp fora do checkout e smoke HTTP de /, assets,
/healthz e API com consulta sintética injetada aprovados. Não é navegador completo.

Build Docker existente tentado: falhou em pip por CERTIFICATE_VERIFY_FAILED
(cadeia do proxy não presente na imagem Python). Nenhuma verificação TLS foi
desabilitada. Docker exigiu BUILDX_CONFIG em /tmp por HOME somente leitura.
Container não validado; pacote/HTTP local validados. Corrigir trust de CA do
build local antes de afirmar imagem validada. Não extrapolar essa falha ao GCP.

API GitHub Forbidden continua impedindo abertura/comentário de PR e leitura de CI.
Sem CI remoto, consulta LIVE, deploy, IAM ou novos gastos. Issue #287 aberta foi
consultada via página pública; PRs #276/#283 inspecionadas via Git. Próximo bloco:
#290, issue aberta consultada, smoke autenticado e plano read-only de rollback.
