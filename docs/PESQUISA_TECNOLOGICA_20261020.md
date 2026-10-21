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


## Continuidade autônoma — rodada de dependências opcionais, 20/10/2026

**Prioridade confirmada:** as bibliotecas opcionais MLForecast, River e DuckDB têm
adaptadores no IVO e declarações em \`pyproject.toml\`, mas não há comprovação
de instalação, resolução travada com hashes, varredura de vulnerabilidades ou
testes com os pacotes instalados na CI padrão. Evitar substituir adaptadores
ou instalar qualquer ferramenta sem essa evidência.

**Código incremental:** \`src/nivon/auditoria_extras.py\` implementa pré-voo
estático, somente leitura e sem dependências adicionais. Examina todos os
grupos do \`pyproject.toml\`, cruza StatsForecast, MLForecast, River e DuckDB
com o catálogo IVO e bloqueia requisitos inseguros/não suportados (URL,
VCS, local paths, markers, extras aninhados), versões contraditórias e
divergência de especificação da mesma distribuição entre grupos opcionais.
Versões de precisão diferente, como 2 e 2.0, são normalizadas nos limites.
Não é um resolver PEP 440 universal; sintaxe não reconhecida é bloqueada
para inspeção manual.

**Teste:** \`tests/test_auditoria_extras.py\` valida os gates com fixtures e
inclui integração com os arquivos verdadeiros do repositório. Executar:

\`\`\`bash
PYTHONPATH=src python -m nivon.auditoria_extras
PYTHONPATH=src python -m unittest discover -s tests -p 'test_auditoria_extras.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
\`\`\`

O resultado \`ANALYSIS_TYPE=STATIC_DIRECT_REQUIREMENTS_ONLY\` jamais deve ser
publicado como SBOM completo, auditoria de CVEs, revisão transitiva ou teste
de bibliotecas instaladas. Um pin exato de dependência direta **não** é lock
transitivo por hash. Flags \`*_verified\` permanecem falsas. A liberação fica
bloqueada para revisão independente de versões, transitivas, vulnerabilidades,
licenças e smoke-tests opcionais em sandbox isolado.

**Dependências:** a branch de pesquisa está empilhada na PR #7 (IVO), que
recebeu commits novos em 20/10/2026. Antes de merge, avaliar regressões
no SHA integrado com o IVO atualizado e coordenação da PR #13.

**Próxima tarefa executável:** produzir o experimento de auditabilidade de
SBOM/lock no ambiente isolado, quando houver revisão de transitivas e rede
autorizada; em paralelo, avaliar se um piloto de fonte oficial autorizada
justifica dlt frente ao orquestrador nativo. Nenhuma aquisição de dados,
instalação ou deploy foi feito nesta rodada.


## Continuidade de 21/10/2026 — evidências externas de CVE (P0)

**Implementação:** `src/nivon/auditoria_evidencias_pacotes.py` + `tests/test_auditoria_evidencias_pacotes.py`. O componente não instala pacotes, não chama APIs e não alega inventariar transitivas. Consome três artefatos **fornecidos manualmente**: (i) lock textual simplificado com `nome==versão --hash=sha256:...` por linha; (ii) relatório original JSON `pip-audit --format json`; (iii) metadados locais com hashes SHA-256 exatos dos três arquivos (incluindo o `pyproject.toml`), instante UTC, serviço, exit code e lista de extras auditados.

**Contratos:** valida hashes das *declarações* dos arquivos, correspondência 1:1 do lock e relatório (inclusive entradas transitivas presentes), atendimento das faixas diretas do NIVON, pacotes ignorados, vulnerabilidades declaradas, divergência de versões, duplicatas, data futura e relatório com mais de 24 horas. A presença de hash SHA-256 no lock não comprova que o arquivo da distribuição foi baixado/verificado; correspondência 1:1 do relatório não prova que todas as transitivas foram resolvidas. Os metadados podem ter sido forjados: nenhum mecanismo de assinatura/autenticidade externa foi implementado. Resultados positivos significam **apenas coerência estrutural de evidências não autenticadas**. Release permanece BLOQUEADA invariavelmente.

**Execução offline após recebimento autorizado de evidências reais:**
```bash
PYTHONPATH=src python -m nivon.auditoria_evidencias_pacotes \
  --lock /caminho/local/requirements-com-hashes.txt \
  --report /caminho/local/pip-audit.json \
  --metadata /caminho/local/metadata.json
```

Para produzir evidências futuramente será necessário um lock verdadeiro gerado e revisado em sandbox seguro, execução do `pip-audit` com serviço oficial, registro verificável de código de saída e de versão do auditor, e armazenamento privado com controle de acesso. **Nenhum dos comandos acima executa scanner CVE real.** A especificação do formato do relatório foi conferida no código oficial de `pypa/pip-audit` (`pip_audit/_format/json.py`). Não incorporar um JSON de auditoria sintético como prova de ausência de vulnerabilidades.

**Revisão pendente:** transformar hashes declarados em prova de pacotes reais e dependências transitivas completas, atestar o executor e integrar um SBOM CycloneDX assinado ou evidência equivalente. Os dois auditores estáticos atuais têm funções parcialmente sobrepostas e precisam de consolidação para evitar duplicidade; o novo validador não altera seus contratos.


## Continuidade de 21/10/2026 — consolidação de parsing de dependências

A sobreposição dos dois auditores estáticos registrada nas seções históricas acima foi **tratada no nível do parser** (as notas anteriores permanecem como histórico):

- **Única interpretação de sintaxe e versões:** `auditoria_extras.analisar_requisito` é o parser compartilhado por `pesquisa_dependencias` e `auditoria_evidencias_pacotes`. Nenhum `pip install` ou serviço externo é invocado.
- **Identidade semântica:** `auditoria_extras.chave_requisito` iguala faixas idênticas com ordem diferente ou zeros finais (por exemplo `>=2.2,<3` e `<3.0,>=2.2.0`) e distingue operadores inclusivos/exclusivos. Não equivale a resolver completo PEP 440, análise de pre-release ou prova de transitivas.
- **Políticas complementares preservadas:** `auditoria_extras` verifica o vínculo de StatsForecast, MLForecast, River e DuckDB ao catálogo IVO e classifica limites de build sem bloqueá-los; `pesquisa_dependencias` exige faixa estritamente crescente ou pin exato para dependência do projeto, trata `setuptools>=68` como risco explícito e produz inventário com hash do `pyproject`. Assim, **não existem mais duas implementações independentes do parser de versões**, embora permaneçam duas saídas para consumidores com responsabilidades distintas.
- **Nova regressão:** `tests/test_consistencia_parsers_dependencias.py` verifica equivalência semântica, conflitos reais entre extras, políticas intencionalmente diferentes e rejeição de URL/marker/extra não autorizado.
- **Limites do gate:** continua sendo somente revisão de declarações. Nunca valida wheel baixado, fechamento transitivo, escaneamento real de vulnerabilidades, licença de transitivas, assinaturas, ambiente instalado ou aptidão de produção.

Próxima prioridade P0 continua a obtenção de evidências independentes autenticadas de uma resolução real de extras opcionais, com hashes conferidos e relatório CVE rastreável. Piloto dlt contra o coletor nativo permanece condicionado à fonte oficial autorizada. Sem alteração em `main`, deploy, instalação ou custo.


## Continuidade de 21/10/2026 — integridade de wheelhouse offline (P0)

**Entregue:** \`src/nivon/auditoria_wheelhouse.py\` e \`tests/test_auditoria_wheelhouse.py\`. A verificação aceita um diretório local **pré-existente** de arquivos \`.whl\` e um lock textual de requisitos \`nome==versão --hash=sha256:...\`, usando o mesmo parser de lock da auditoria de relatórios JSON. Não baixa, instala, importa nem executa dependências de terceiros. Exige exatamente um wheel por distribuição esperada e rejeita arquivos extras, ausência de pacote, symlinks, diretórios e sdists.

**Evidência que este gate efetivamente demonstra:** o SHA-256 calculado **sobre os bytes presentes no diretório local** pertence ao conjunto de hashes declarado no lock. Também confere a identidade da distribuição/versão no filename, no \`.dist-info\` e nos cabeçalhos \`METADATA\`/\`WHEEL\`, sem extrair arquivos. Rejeita caminhos ZIP inseguros, duplicação de membros, symlinks dentro do ZIP, arquivos criptografados, metadados excessivos, arquivos grandes e expansão desproporcional. Testes usam wheels gerados sinteticamente na memória. A mesma descrição não deve ser usada como prova de que o lock foi produzido por resolvedor confiável.

**Uso futuro com artefatos locais autorizados:**

\`\`\`bash
PYTHONPATH=src python -m nivon.auditoria_wheelhouse \
  --lock /local/requirements-com-hashes.txt \
  --wheelhouse /local/wheelhouse
\`\`\`

**Limites obrigatórios:** não há prova de origem/autenticidade dos hashes publicados ou do executor; a ferramenta não verifica assinatura de wheel, \`RECORD\` interno, compatibilidade ABI/plataforma, marker de dependência, fechamento transitivo, licença, advisories/CVEs ou ambiente instalado. Ela suporta um subconjunto numérico restrito de versões para falhar fechada; wheels fora dele não são homologados automaticamente. Mesmo um wheelhouse 100% consistente produz \`approved_for_install=false\` e \`approved_for_production=false\`.

**Próximo gate executável:** correlacionar bytes/hashes verificados com o relatório \`pip-audit\`, adicionar comprovação verificável da origem dos artefatos e resolução completa das dependências, e depois executar auditoria CVE real + teste de importação em ambiente sandbox homologado. Não publicar resultados de fixtures como scan CVE real. Sem instalações, rede operacional, merge, deploy ou custos nesta rodada.
