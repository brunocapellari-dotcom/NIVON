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
