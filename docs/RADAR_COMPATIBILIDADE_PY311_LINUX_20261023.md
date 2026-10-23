# NIVON — Compatibilidade de wheels e primeiro mapa de dependências transitivas

**Data de corte da análise:** 23/10/2026, baseada nas nove versões candidatas obtidas de metadados reais do PyPI e avisos OSV. **Estado:** pesquisa e inspeção de metadados, sem instalação/download de wheels e sem aprovação de produção.

## Resultado da comparação de infraestrutura Linux

O conjunto de dados é o mesmo para os dois perfis: CPython 3.11, arquitetura `x86_64`, mudando somente a hipótese explícita de glibc mínima.

| Pacote direto | Wheel tag disponível com glibc >=2.17 | Wheel tag disponível com glibc >=2.28 | Evidência de arquivo publicado |
|---|---|---|---|
| agrobr 2.0.0 | Sim | Sim | `py3-none-any` |
| duckdb 1.5.6 | Não no subconjunto verificado | Sim | `cp311-cp311-manylinux_2_26_x86_64.manylinux_2_28_x86_64` |
| mlforecast 1.1.0 | Sim | Sim | `py3-none-any` |
| openpyxl 3.1.5 | Sim | Sim | `py2.py3-none-any` |
| pandas 2.3.3 | Não no subconjunto verificado | Sim | `cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64` |
| pdfplumber 0.11.10 | Sim | Sim | `py3-none-any` |
| river 0.26.1 | Não no subconjunto verificado | Sim | `cp311-abi3-manylinux_2_28_x86_64` |
| scikit-learn 1.9.1 | Não no subconjunto verificado | Sim | `cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64` |
| statsforecast 2.1.1 | Não no subconjunto verificado | Sim | `cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64` |

**4/9 possuem tags anunciadas reconhecidas para glibc 2.17; 9/9 para glibc 2.28.** Isso avalia tags e intervalos `Requires-Python` **declarados nos metadados de distribuição** com um analisador deliberadamente conservador e incompleto. Não comprova que os pacotes funcionarão no Linux, que a ABI é de fato adequada, que os arquivos de terceiros são autênticos, ou que os pacotes transitivos são compatíveis. A imagem efetiva do Google Cloud **não foi identificada nem homologada**; glibc 2.28 é um parâmetro de pesquisa para a futura definição da imagem, não uma configuração aplicada.

Fonte normativa: [tags de compatibilidade de plataformas Python](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/) e [formato de wheel](https://packaging.python.org/en/latest/specifications/binary-distribution-format/).

## Separação do passivo transitivo

O PyPI expõe `Requires-Dist` para os nove candidatos. O NIVON agora registra **98 nomes distintos declarados**, dos quais **93 não pertencem ao conjunto dos nove candidatos diretos**. A triagem separa:

- **34 nomes externos aparecem em pelo menos um requisito sem marcador** (prioridade P1 para futura resolução real);
- **1 nome externo foi encontrado em requisitos condicionados por marcadores de ambiente**;
- **67 nomes externos são mencionados por requisitos com `extra` ou seletores de extras**.

As três contagens podem **se sobrepor**: uma mesma distribuição pode aparecer em mais de uma categoria. Portanto não somar os valores como se fossem pacotes instaláveis distintos. Os marcadores `extra == ...`, `python_version`, `sys_platform`, operações booleanas e extras solicitados **ainda não foram interpretados segundo a PEP 508**. A contagem de 93 é de *nomes declarados*, não de dependências efetivamente requeridas ou versões resolvidas.

## Implementação e validação

- `src/nivon/inspecao_compatibilidade_wheels.py`: triagem offline de `Requires-Python`, tags `py3-none-any`, `cp311-cp311`, `abi3` e `manylinux_2_X_x86_64` em perfis glibc 2.17 e 2.28; lista de wheels com correspondência de metadados, desconhecidos e rejeitados; três grupos de dependências declaradas.
- `src/nivon/radar_pypi_osv.py`: passou a preservar a declaração `requires_python` também **por arquivo** do índice PyPI, não apenas no nível do release.
- `tests/test_inspecao_compatibilidade_wheels.py`: regressões integradas de nove pacotes, Linux/Windows/macOS/ARM, tags comprimidas, `Requires-Python`, marcadores e bloqueios de produção.
- `.github/workflows/radar-pypi-osv.yml`: executa os dois perfis sobre o mesmo JSON **real** de nove candidatos, publica relatórios individuais, checksum, fontes PyPI/OSV e identificação do runner GitHub. O campo `gcp_runtime_verified=false` impede confundir o runner da CI com o Google Cloud.

## Próximas etapas de engenharia

1. Validar a configuração alvo real do **Google Cloud** (imagem, Python, arquitetura e glibc), antes de homologar os nove candidatos, sem ativar recursos pagos ou deployments não autorizados.
2. Construir um resolvedor PEP 508/440 confiável e obter lock transitive para cada extra, priorizando os nomes efetivamente incondicionais e avaliando corretamente marcadores de ambiente/extras. Não confundir enumeração de nomes com resolução.
3. Fazer download autorizado dos arquivos selecionados, comparar SHA256 dos bytes com índice PyPI, conferir RECORD/wheel tags/assinaturas e auditar efetivamente SBOM, avisos e licenças; nenhum download ou instalação foi feito nesta rodada.
4. Executar smoke-tests reais em sandbox isolado somente após revisão da cadeia de suprimentos. `approved_for_install=false` e `approved_for_production=false` permanecem obrigatórios.

A PR #27 permanece em draft; a coleta de metadados e os testes não autorizam alteração da branch principal, instalação nem deploy.
