# Arquitetura do NIVON — ESQUELETO PROVISÓRIO

**Situação:** PENDENTE de consolidação após o merge de F2, F3 e F4. Este documento representa o **alvo aprovado**, não o estado comprovado de execução.

## Princípios
1. Google Cloud como único ambiente de execução, GitHub apenas para código, CI e gestão.
2. Um terminal privado em Cloud Run, acesso via IAP, nenhum segundo frontend.
3. Um coletor em Cloud Run Job, acionado de modo controlado; evitar dezenas de workflows.
4. Uma definição canônica de fontes em `config/fontes.yaml`.
5. Separação entre dados brutos, preparação, entidades verificadas e camada de consumo; jamais promover dados sintéticos a reais.
6. Proveniência, competência, referência, publicação e coleta registradas, sem confundir programação com realizado.

## Organização-alvo
- `nucleo/`: contratos, modelos, identidades e proveniência (**PENDENTE F2/F3**).
- `fontes/<fonte>/`: adaptadores independentes e catálogo (**PENDENTE F4**).
- `carga/`: ingestão, normalização, validação e persistência (**PENDENTE F4**).
- `analise/`: modelos e indicadores com rastreabilidade (**PENDENTE F3/F4**).
- `terminal/`: única interface privada (**PENDENTE F3**).
- `ops/`: orquestração, implantação, observabilidade e recuperação (**PENDENTE F2/F5**).
- `experimental/`: pesquisas isoladas sem efeito na operação (**PENDENTE**).

## Armazenamento-alvo
- `nivon_raw`: evidência bruta e registro de origem.
- `nivon_stage`: preparação e verificações.
- `nivon_core`: entidades e fatos consolidados.
- **Quarto dataset e contratos finais: PENDENTE F2/F4**. Não inventar nome ou declarar tabelas existentes.

## Componentes e integrações
| Componente | Responsabilidade | Estado documental |
|---|---|---|
| Terminal Cloud Run + IAP | Acesso privado e consulta read-only | PENDENTE F2/F3/F5 |
| Coletor Cloud Run Job | Coleta versionada por fonte | PENDENTE F2/F4 |
| BigQuery | Persistência auditável | PENDENTE F2/F4 |
| GitHub Actions | Até seis workflows após consolidação | PENDENTE F2 |
| Configuração | Até oito variáveis e catálogo único | PENDENTE F2/F4 |

## Critérios de conclusão
Atualizar **somente após merges F2, F3 e F4** e confrontar conteúdo com paths reais, CI, revisão em produção, fontes efetivamente operantes, IAM e custos. Até lá, não usar este documento como prova de go-live.

Ver [Operação](OPERACAO.md), [Fontes — F4](FONTES.md), [Segurança — F5](SEGURANCA.md).
