# NIVON — Bootstrap mínimo de APIs privadas

**Escopo:** carregar na `main` apenas os módulos de verificação protegida de **USDA FAS/PSD, ANA HidroWebService e INMET BDMEP**, isolados das centenas de arquivos ainda em revisão na PR #61.

## Segurança de execução

- O workflow `.github/workflows/testes-acessos-isolados.yml` executa **somente testes offline em pull requests**, sem injetar secrets, chamar os serviços nem persistir dados. `GITHUB_TOKEN` fica somente leitura.
- O workflow `.github/workflows/acessos-privados.yml` só oferece **`workflow_dispatch` no branch `main`**, requer o Environment `nivon-fontes-privadas` e usa **`preflight` como padrão**; `live` exige escolha adicional.
- Preflight apenas verifica presença/formato da credencial, **não faz autenticação** nem demonstra permissão de acesso, coleta ou armazenamento.
- O modo live tenta apenas uma fonte por execução. INMET faz download de ZIP para diretório temporário e não cria artefatos.
- Nenhuma operação automática ou periódica de coleta, publicação ou modelo foi habilitada.
- O repositório NIVON é público, e os 4 valores precisam ficar **exclusivamente** nos secrets do Environment GitHub, nunca em commits, parâmetros URL, mensagens, logs ou serviços Vercel.

## Secrets exigidos do Environment (nomes somente)

`AGROBR_USDA_API_KEY`, `NIVON_ANA_IDENTIFICADOR`, `NIVON_ANA_SENHA`, `NIVON_INMET_BDMEP_URL`.

A permissão de environment deve continuar `Selected branches and tags` → **somente `main`**. A presença/valor das credenciais precisa ser confirmada pelo preflight, não apenas pela informação de que foram cadastradas. Se um secret estiver ausente, o job falha fechado.

## Roteiro de revisão e ativação

1. Revisar a PR isolada e sua CI offline; não confundir CI verde com autenticação real.
2. Avaliar efeitos da integração na implantação de produção do Vercel, inclusive eventuais prévias automáticas.
3. Após autorização de merge, confirmar a política do Environment e a disponibilidade do workflow na `main`.
4. Iniciar manualmente cada fonte no modo **preflight** e conferir apenas os status sanitizados.
5. Em execução separada e expressamente controlada, selecionar `live` — USDA FAS, ANA e INMET individualmente — validando a fonte, os dados, direitos por operação, frescor, tamanho e persistência; **não** homologar NASS, WASDE ou INMET contínuo usando apenas esses acessos.

## Proveniência

Código isolado do HEAD GitHub da PR #61: `6dd76b40d5e9ea6c532183048930c92e8f4f5850`. Reutiliza módulos e testes já aprovados com fixtures no NIVON, sem dependências externas. A PR #61 continua aberta para integração ampla e revisões independentes.

**Importante:** Esta PR não contém o catálogo completo nem motores do NIVON. Ela não substitui a integração maior.
