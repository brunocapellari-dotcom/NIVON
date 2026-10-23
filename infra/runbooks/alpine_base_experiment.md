# NIVON — Avaliação experimental da base Python Alpine 3.23

**Escopo:** apenas worker mínimo offline, Python stdlib, AMD64 e ARM64. Não alterar a base Debian canônica.

- Imagem oficial candidata `python:3.11.17-alpine3.23`, índice multiarch `sha256:924d53e01cee5204d35fbcfb71b6c1568c857d7c31141f960ff6a37e111ecc7f`, observado no Docker Hub em 21/10/2026. Não usar tag móvel sem pinagem.
- Baseline: `python:3.11-slim-trixie@sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8`, com a mesma remoção das ferramentas Python de packaging. Isso isola a diferença entre Debian e Alpine.
- `.github/workflows/infra_alpine_benchmark.yml`: runners nativos AMD64 e ARM64; build isolado sem rede nos passos RUN, arquivos de contexto limitados, execução nonroot/read-only/cap-drop e flags externas explicitamente desabilitadas. Valida stdlib SQLite, TLS, fuso, self-check e job sintético com idempotência em diretório privado.
- Trivy v0.76.0 com tarball SHA-256 fixado para cada arquitetura, mesmo banco em cada comparação; gera CycloneDX para candidata sem publicar relatórios brutos.
- `src/nivon/infra_alpine_compare.py` recusa artefatos/arquiteturas não homologados, resultados vazios e SBOM vazio. Conta todos HIGH e CRITICAL por pacote; melhoria numérica não implica segurança ou autorização.
- **Risco material:** Alpine usa musl, não glibc. Compatibilidade e wheels de pandas/numpy/psycopg2/geo/libs nativas não são comprovadas por worker só-stdlib. Necessária auditoria de todos os conectores reais, segurança da distribuição, atualização de packages e ARM64 em OCI antes de qualquer migração.
- O workflow é experimental, não cria release, não faz upload de imagens, não consome credenciais cloud e não muda gate `infra_supplychain.yml`. Não classificar CI verde como deploy ou armazenamento real validado.

**Próximo passo:** inspecionar evidências e eventual redução real de CVEs; se houver risco crítico Alpine, descartar candidato. Se a comparação for favorável, ainda exigir auditoria de pacotes de runtime completos e segurança independente antes de nova decisão.

## Verificação de compatibilidade ampliada

Como a imagem Alpine usa musl, a simples aprovação do worker stdlib é insuficiente. Um novo passo do workflow executa **toda a suíte `unittest discover -s tests -v`** diretamente dentro da imagem Alpine nativa de cada arquitetura, com o repositório montado somente leitura, sem rede, UID 65532, capacidades retiradas e `/tmp` efêmero com limite. Uma falha ou omissão de biblioteca é evidência de incompatibilidade a investigar, não motivo para relaxar testes. O resultado não comprova compatibilidade com os extras futuros `agrobr`, `statsforecast`, `pdfplumber` e `openpyxl`; a instalação e os wheels devem ser avaliados separadamente.
