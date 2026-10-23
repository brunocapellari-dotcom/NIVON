# NIVON — Homologação de wheels de dependências opcionais em Alpine

Data: 21/10/2026. Somente experimento, nunca liberação de produção. A imagem Debian canônica e seus gates continuam inalterados.

## Grupos retirados do contrato canônico pyproject.toml
- `agro`: `agrobr==2.0.0`.
- `forecast`: `pandas>=2.2,<3` e `statsforecast>=2,<3`.
- `ports`: `pdfplumber>=0.11,<1`.
- `excel`: `openpyxl>=3.1,<4`.

A execução valida exatamente esses grupos e versões antes de rede; mudança exige revisão de segurança. O Agrobr 2.0.0 é distribuído como wheel universal, mas **não comprova dependências transitivas nem licença dos dados**. Sua licença de código é MIT; dados obtidos por fontes conectadas mantêm direitos próprios, inclusive CEPEA/ESALQ com CC BY-NC 4.0 conforme PyPI do próprio Agrobr.

## Desenho do ensaio
`.github/workflows/infra_optional_wheels.yml` testa separadamente os quatro grupos, em runner GitHub público **nativo AMD64 e ARM64** (oito jobs). Usa a imagem oficial Alpine Python 3.11.17 com digest imutável já testado no benchmark. **Não modifica a imagem principal nem a candidata `Dockerfile.worker-alpine`.**

Fase 1: contêiner nonroot, sem capabilities, raiz read-only, apenas PyPI como índice Python, usa `pip download --only-binary=:all:` com limite de duração; sem build de distribuições fonte e sem pacotes do sistema. Os arquivos ficam em pasta efêmera privada por grupo no runner, sem upload.

Fase 2: contêiner separado, **sem rede**, instala somente wheels já baixadas no destino efêmero e faz smoke test de importações. Para Excel também cria um XLSX simples em memória, sem tocar dados pessoais; não faz chamadas Agrobr/CEPEA/IMEA reais. A falha de qualquer grupo resulta no job vermelho; não significa incompatibilidade definitiva até distinguir indisponibilidade temporária de PyPI, falta de wheel compatível, versão/ABI e erro de importação. Para não expor informações do runner, stdout/stderr detalhados do pip são suprimidos; a auditoria informa apenas fase, grupo, contagem e bytes.

## Limites e próxima decisão

- Não há lock de dependências transitivas e verificações de licenças/assinaturas de todas as wheels, SBOM final com os extras ou análise CVE dos extras instalados. **CI verde de wheels não autoriza release.**
- Execução `pip install` utiliza somente rodas binárias locais e roda offline, mas um import pode executar código de terceiros; o contêiner é nonroot, sem rede, com limites e sem credenciais. 
- Compatibilidade glibc/musl, testes E2E dos coletores, OCI real, clima, frete, bases de dados e APIs permanecem pendentes.
- Em caso de falhas, agrupar por pacote/version ABI e priorizar a menor solução segura que não implique liberar fontes de dados licenciadas.

Não realizar deploy, transferência de arquivo bruto para outro serviço, publish de imagem, cobrança nova ou ativação de coletores.

## Primeira rodada de compatibilidade (ainda sem diagnóstico do pacote faltante)

[Execução 39671894570](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671894570) no commit `5b41a7550e31cf113e497d1fcf62b89c43dcc2ef`: `excel` e `ports` passaram em AMD64 e ARM64 (resolução apenas wheel, instalação offline e smoke); `agro` e `forecast` reprovaram a fase de download de wheels em ambas arquiteturas. Isso não prova incompatibilidade definitiva; pode ser wheel transitive indisponível ou outro erro PyPI. Um classificador foi acrescentado para extrair somente nomes públicos de requisitos não resolvidos, sem imprimir stdout/stderr brutos, tokens, URLs ou caminhos.

## Segunda etapa — comparação Debian glibc por dependências incompatíveis com musl

Agrobr e StatsForecast tiveram download binário bloqueado no Alpine em ambos os runners: `duckdb` e `statsforecast` sem wheel compatível, respectivamente. Assim, o workflow único foi ampliado para testar os mesmos grupos sobre **Debian Trixie com digest fixo**, nas duas arquiteturas. Isso não suprime os achados CVE da base Debian: a imagem atual continua bloqueada, e um sucesso do ensaio de wheel significa somente viabilidade técnica de instalação/importação em contêiner de teste. O resultado Debian precisa ser auditado com as versões efetivas e SBOM/CVEs de uma imagem de runtime completa antes de deploy.

## Diagnóstico de instalação versus importação (Debian)

Na execução comparativa [39672663044](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39672663044), os grupos `agro` e `forecast` no Debian conseguiram resolver wheels binárias em AMD64 e ARM64, mas a etapa posterior de instalação/importação offline falhou. O scanner de pacotes Alpine continua bloqueando downloads binários para `duckdb` e `statsforecast`. O código passou a marcar `WHEEL_DOWNLOAD`, `OFFLINE_INSTALL` ou `OFFLINE_IMPORT` e reconhecer somente nomes públicos de bibliotecas/módulos em casos de erro. Logs brutos continuam sem publicação. Nenhum grupo com falha pode ser considerado homologado.

## Evidência final da comparação e decisão conservadora

O ensaio único [GitHub Actions 39673348590](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39673348590), código do ensaio `790b17f473a2be75a78e63bff27421aeaa91f10f`, executou **12 ambientes** (AMD64 e ARM64 nativos): 8 no Alpine, 4 no Debian. Resultados: Alpine `excel` e `ports` instalaram wheels localmente e passaram smoke offline em ambas as arquiteturas; Alpine `agro` parou em wheel `duckdb` e `forecast` parou em `statsforecast` antes de instalar; Debian `agro` e `forecast` resolveram wheels e completaram a instalação offline/importações em ambas as arquiteturas. O primeiro ensaio Debian com espaço temporário insuficiente/diagnóstico genérico foi corrigido ampliando **apenas o tmpfs da fase de instalação no CI** e adicionando `--no-compile`; não houve mudança na imagem de runtime. O resultado comprovado substitui as observações preliminares acima.

A matriz `infra/compatibility_observed.v1.json` registra **evidência estática datada**, não uma autorização de roteamento de workers. São duas estratégias candidatas: Alpine mínimo para infraestrutura e trabalho stdlib; Debian glibc para motores analíticos que dependem de DuckDB/StatsForecast. A adoção de duas imagens **não foi implementada**. Debian ainda tem CVEs altas no worker canônico e Alpine ainda não suporta os grupos analíticos sob política apenas-wheels. Precisam ser revisados lock das versões transitivas, licenças de código e dados, SBOM/CVEs da imagem **com extras instalados**, execução funcional E2E do Agrobr/StatsForecast e custos/infra OCI.
