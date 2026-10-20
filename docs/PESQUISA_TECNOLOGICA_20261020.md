# NIVON — Pesquisa tecnológica e lacunas priorizadas (20/10/2026)

**Estado:** auditoria de repositório + triagem de tecnologia. **Não há homologação, instalação, coleta real, treinamento ou implantação neste PR.**

## Linha de base

- A branch main contém apenas README e declara operação não homologada.
- A PR #1 contém o núcleo de fontes, rotas, parsers, versões históricas e motores em testes sintéticos; nenhum módulo deve ser refeito sem evidência de ganho.
- A PR #7 possui catálogo de **38 tecnologias** em `config/ivo_ferramentas_github.v1.json`: StatsForecast, MLForecast, River, DuckDB, Frictionless, Xarray, entre outras. Este incremento **estende** o catálogo, não o replica.
- PRs #3, #6, #9, #12 e #13 contêm desenvolvimento setorial e coordenação das 14 frentes; convergência fica a cargo da frente de integração.

## Lacunas P0 e seus gates

| Lacuna verificada | Experimento necessário | Gate de aceite |
| --- | --- | --- |
| Coleta real recorrente ainda não homologada | Um coletor oficial autorizado, com snapshots antes/depois de três edições; comparar dlt ao mecanismo atual | Idempotência, hash do bruto, vintage, datas e permissões, falha parcial, restore |
| Dependências opcionais sem teste integrado com as bibliotecas efetivamente instaladas | Executar extras em sandbox após revisão de lock e dependências; avaliar pip-audit | SBOM, relatório CVE, versões, hashes, logs e teste de integração |
| Modelos sem rótulos reais certificados, as-of e skill fora da amostra comprovados | Reutilizar os modelos e benchmarks existentes do IVO | Walk-forward, baseline, calibração, holdout temporal, direitos de dados e revisão independente |
| PRs empilhadas sem integração em main | Regressões coordenadas pela PR #13 | CI no SHA integrado, revisão de riscos, custo e licença, gates de release |

**P1:** schemas de CSV/planilhas e schema drift: primeiro ensaiar **Frictionless** (já listado no IVO) contra validadores locais com três layouts reais autorizados. Proveniência heterogênea: adaptar o contrato local antes de ponderar OpenLineage.

## Pesquisa GitHub — apenas candidatos incrementais

| Componente | Decisão | Por quê |
| --- | --- | --- |
| [dlt](https://github.com/dlt-hub/dlt) | BENCHMARK/P0 | Incremental load, estado e schema contracts. Risco de duplicar orquestrador e snapshots; não adotar sem ganho mensurável |
| [pip-audit](https://github.com/pypa/pip-audit) | EVALUATE/P0 | Auditoria de vulnerabilidades conhecidas e geração de SBOM para pacotes opcionais; não usar a função de correção automática |
| [OpenLineage](https://github.com/OpenLineage/OpenLineage) | RESERVE/P1 | Metadados padronizados de linhagem; ledger existente pode ser suficiente sem serviço adicional |
| [Pandera](https://github.com/unionai-oss/pandera) | RESERVE/P1 | Schemas para DataFrames; Frictionless e validadores existentes têm precedência |

**Evidência verificada em 20/10/2026:** metadados GitHub e arquivos de licença: dlt, pip-audit e OpenLineage — Apache-2.0; Pandera — MIT. Atividade recente observada no GitHub, mas **sem análise de advisories, CVEs, dependências transitivas, direitos de dados ou compliance comercial integral**. Licença declarada do código não concede direitos sobre datasets, modelos, conectores ou serviços. Nenhum código de terceiros foi copiado.

## Integração entregue

- `config/pesquisa_tecnologica_delta.v1.json`: somente quatro repositórios ainda ausentes da lista IVO; decisão, overlap, evidência e experimento por candidato.
- `src/nivon/pesquisa_tecnologica.py`: auditor offline com biblioteca padrão; une o inventário IVO existente ao delta, recusa IDs e repositórios repetidos, URLs GitHub inválidas, evidência cruzada, flags permissivas, declarações de adoção sem revisão, datas futuras e pacotes já declarados no pyproject.
- `tests/test_pesquisa_tecnologica.py`: 15 testes sintéticos de segurança, deduplicação e CLI local; executar também pela CI do repositório.
- Não executa comandos externos, instala dependências, chama API de terceiros, acessa rede ou concede direitos de produção.

Reproduzir com Python 3.11+ na branch empilhada sobre a PR #7:

```bash
PYTHONPATH=src python -m nivon.pesquisa_tecnologica --resumo
PYTHONPATH=src python -m unittest discover -s tests -p 'test_pesquisa_tecnologica.py' -v
```

**Próxima ação:** medir uma prova dlt **apenas depois** da liberação jurídica/técnica de uma edição histórica oficial e comparação com a implementação existente. Paralelamente, rever e executar os extras do IVO em sandbox restrito, sem gastos ou ativação de produção.

**Regra:** o resultado deste auditor é inventário e bloqueios, não atestado de segurança ou aptidão operacional. A política do delta mantém `allow_install: false` para todos os registros, mesmo quando uma adoção for tecnicamente aprovada.
