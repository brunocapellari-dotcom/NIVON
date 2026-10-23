# Candidato analítico Distroless — benchmark sem produção

Caminho de P0 da infraestrutura: reduzir os **44 HIGH** presentes na imagem analítica experimental Debian Trixie sem desligar o Trivy. O projeto [GoogleContainerTools/distroless](https://github.com/GoogleContainerTools/distroless) mantém `gcr.io/distroless/cc-debian13:nonroot` para amd64 e arm64.

A abordagem mantém **exatamente** o Python 3.11 e as 59 wheels/hashes travadas por arquitetura, reaproveitando a imagem experimental Debian previamente construída (não redownloada). O Dockerfile multistage copia `/usr/local`, `/opt/nivon/deps` e `/app` da imagem já construída para runtime distroless, sem executável `sh`, `apt` ou `pip` via ENTRYPOINT. Se houver dependências de bibliotecas nativas não incluídas na base distroless, o teste falhará. Não copiar indiscriminadamente `/usr/lib`/bibliotecas vulneráveis apenas para ficar verde.

O CI pega a tag pública para pesquisa, **resolve e verifica o digest do índice remoto antes do build**, usa esse digest como `--build-arg DISTROLESS_BASE`, valida arquitetura e tenta o mesmo teste analítico `StatsForecast.Naive` offline. Fase posterior compara scans Trivy e inventário CycloneDX com `agrobr,pandas,statsforecast`. O digest resolvido deve ser versionado em gate próprio antes de possível adoção; somente testar tag sem fixá-la não configura referência imutável para produção.

**Gates:** não autorizar imagem sem prova de ABI/execução, scanner da imagem final em AMD64/ARM64, lock das dependências, licenças/fontes, rede zero, UID não privilegiado, integridade, recuperação, revisão externa, cloud IAM/quotas e autorização humana. Mesmo 0 HIGH/CRITICAL na candidata não significa ausência de risco. A imagem Debian original e workflow de supply-chain canônico permanecem bloqueados, sem `ignore-unfixed` ou waiver.

## Resultado do primeiro build e diagnóstico obrigatório

[CI 39944743953](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944743953), SHA `280ab0a94d4fa60970161e37f001d8aef8400fda`: builds multiarch concluídos com sucesso a partir do digest oficial `gcr.io/distroless/cc-debian13@sha256:83b9b50586253821cf63ffcec87d3d94265a093ad30da232039af962dd8f4edf`; ambos os jobs falharam no teste de execução `ANALYTICS_EXPERIMENT_FAILED`. As exceções eram propositalmente ocultas. O digest foi fixado no Dockerfile para evitar deriva da tag; o workflow executa agora um diagnóstico offline estritamente limitado a nomes de módulos, classe de erro e SONAME faltante, sem traceback nem segredos. **Não há compatibilidade homologada nesta etapa.**
