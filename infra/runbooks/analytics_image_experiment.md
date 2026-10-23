# NIVON — Ensaios E2E da imagem analítica com extras (somente CI)

**21/10/2026.** Imagem experimental Debian Python 3.11/Trixie digest imutável, duas arquiteturas nativas AMD64 e ARM64. Workload sem rede e com série sintética; nenhum coletor real é iniciado, fonte licenciada é consultada ou serviço de cloud provisionado.

O Dockerfile `infra/docker/Dockerfile.analytics-experiment` possui estágio isolado com wheelhouse local gerado no runner. O runner usa somente `pip download --only-binary=:all:` do índice público PyPI e verifica hash SHA-256 dos arquivos efêmeros (não publica lock nem artefatos). BuildKit recebe o diretório por *named build context* `wheelhouse`, executa `pip install --no-index` e copia somente `/opt/nivon/deps` para o runtime final. Não persiste tarballs de wheel no runtime. Remove gestores globais de empacotamento no runtime. Não usa `apt-get`, `curl`, Docker push, secrets, Oracle, deploy, dados externos ou APIs Agrobr.

Em cada arquitetura, o candidato executa como UID 65532, capabilities eliminadas, raiz readonly e rede zero. Faz importação Agrobr 2.0.0 e teste funcional StatsForecast/Naive com pandas em série de **8 dias sintéticos**, prevendo duas observações iguais a 8. Executa também self-check do worker. Falhas de importação ou previsão reprovam o job experimental; não se introduzem waivers.

A comparação Trivy v0.76.0 gera dois JSON da imagem Debian baseline vs runtime com extras, usando o mesmo banco na execução, e um SBOM CycloneDX da candidata. `src/nivon/infra_analytics_audit.py` publica somente quantidade de achados/itens e confirma que Agrobr/pandas/StatsForecast aparecem no SBOM; o relatório **jamais** aprova produção, ainda que zerado. Sem upload de relatórios. Todas as versões transitivas permanecem NÃO travadas, e a licença dos dados NÃO é inferida da licença dos pacotes.

**Gates externos permanecem fechados:** CVEs do sistema Debian, validação de direitos de fontes, revisão independente de imagem final e dependências, obtenção de segurança de cadeia de suprimentos, OCI IAM/quota/custo, backups remotos restore, ambientes reais e homologação. Sem alteração da imagem principal do worker.
