# NIVON — Inteligência de Mercado, Indústria e Logística

Plataforma independente de inteligência agrícola, agroindustrial e logística, com foco inicial em Mato Grosso e no Brasil e expansão para mercados globais.

**Estado: desenvolvimento iniciado; NÃO HOMOLOGADO para uso operacional.** Auditorias de 16/10/2026: **GO COM CONDIÇÕES para implementação**, não para go-live.

## Decisões permanentes

- GitHub público, sem credenciais, informações privadas ou séries restritas. Os CSVs versionados em `tests/fixtures` são **inteiramente sintéticos**.
- Custo adicional ideal **R$ 0**. Nenhum deploy ou gasto foi autorizado/realizado nesta entrega.
- Fontes têm autorização separada por operação: leitura, coleta, armazenamento, transformação e redistribuição. `PENDENTE` = **bloqueada**.
- Não trocar dado OBSERVADO por ESTIMADO, PROJETADO ou INFORMADO. Dados nulos não viram zero.
- Preservar competência, referência, publicação, coleta e histórico de revisões. Não misturar ano civil e safra sem regra explícita.
- CEPEA (440 L de etanol, 331 kg DDG, 20,4 L de óleo/t milho) = **parâmetro de margem**, não trio automaticamente válido para balanço físico.
- Volumes ANTT identificados por NCM são **amostrais**, não consumo final nem volume nacional/estadual total. Municípios com fábrica e terminal são `AMBIGUO`.
- Programação portuária não equivale a operação concluída. AIS contínuo não está ativo.
- Reaproveitamento do AgroLog e de outros projetos deve preservar direitos, testes e proveniência; sem introduzir dependência forçada de GCP ou Holding.

## Implementação do PR #1

**Motores e infraestrutura local, sem dependências externas em execução:**

- `src/nivon/motores.py` — cenário de consumo por CAGR histórico (3–5 anos), sensibilidade anual, parâmetros de margem CEPEA, verificação de massa, recorte NCM e direitos por fonte.
- `src/nivon/balancos.py` — balanços por Brasil/UF, conservação física, consumo decomposto sem dupla contagem e calendário coerente.
- `src/nivon/historico.py` — seleção de edições conhecidas até a data de corte (visão *as-of*).
- `src/nivon/previsoes.py` — backtest temporal de CAGR contra referência ingênua, sem promover modelos sem evidência.
- `src/nivon/ingestao.py` — CSV local com limites, cabeçalho, hash SHA-256, datas, delimitação e codificação explícitas.
- `src/nivon/importadores.py` — mapeamento exato do layout de cada publicação, sem supor cabeçalhos reais da ANTT/MAPA. Exige domínios conhecidos de fábrica e carga própria.
- `src/nivon/destinos.py` — regiões com fábricas MAPA de classificação RAÇÃO × terminais × destinos ANTT, NCM amostral, recorrência mensal e rejeição de recortes mensais duplicados.
- `src/nivon/cadastro_derivado.py` — carrega lista agregada de municípios com fábrica de ração candidata, sem CPF/CNPJ/razão social.
- `src/nivon/analise_local.py` — execução offline completa com ANTT e **MAPA em CSV bruto autorizado ou em JSON agregado sem identificadores**.
- `src/nivon/portos.py` — cadastro canônico inicial de dez portos e contagem prudente de escalas; IMO sozinho não representa uma escala.
- `src/nivon/lineup_html.py` — leitura offline de HTML tabular previamente salvo, com mapeamento de cabeçalhos e estado exclusivamente PROGRAMADO.
- `src/nivon/coleta_web.py` — aquisição HTTPS bloqueada por padrão, com allowlist de host, sem redirects, MIME, tamanho e hash. **Não habilitada nem testada com fontes reais.**

`config/portos_brasil.v1.json` é catálogo, não declaração de que os dez portos estejam operacionais. Nenhum conector portuário está homologado.

## Primeiro conjunto real examinado (MAPA/SIPEAGRO)

A execução [GitHub Actions 39000174173](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39000174173) examinou o CSV público MAPA e gerou **somente uma lista derivada de municípios**. O arquivo de origem tinha 18.003 linhas; o filtro Ativo + Fabricante + Alimentação Animal + Ração selecionou 2.029 registros de cadastro em 1.168 municípios. Esses números **não representam plantas exclusivas por município, toneladas processadas ou consumo**. Não há segmentação comprovada de aves e suínos.

- Mapeamento das nove colunas oficiais: `config/sipeagro_esquema_verificado.v1.json`.
- Fonte e licença indicada no catálogo: https://dados.agricultura.gov.br/dataset/sipeagro/resource/378b184b-67bd-48fa-9901-17bb7a0700fb — Creative Commons Attribution.
- O agregado municipal derivado é publicado **como artefato temporário do CI por três dias**, após checagem contra identificadores individuais; nunca se publica o CSV bruto no GitHub.
- Dados são snapshot pontual de cadastro público, sem atualização recorrente ativada e sem homologação do consumo industrial.

## Reproduzir com dados sintéticos

Executar na raiz com Python 3.11+:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon
PYTHONPATH=src python -m nivon.analise_local --config config/contrato_exemplo_sintetico.json
```

No PowerShell:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m nivon
python -m nivon.analise_local --config config/contrato_exemplo_sintetico.json
```

O exemplo de fluxos contém apenas **dados inventados**, para demonstrar 600 toneladas identificadas em destino AMBÍGUO e 50 toneladas sem NCM. Não é medição do mercado.

A suíte do projeto é executada nos checks do PR, usando fixtures sintéticas. **A execução do commit atual precisa ser confirmada no GitHub Actions; teste unitário não comprova homologação de todas as fontes.** Ver [workflow](https://github.com/brunocapellari-dotcom/NIVON/actions).

## Próximos gates

1. Validar o código e executar a suíte integral do PR em ambiente limpo, depois registrar resultado e eventuais correções.
2. Conferir layouts e direitos dos CSVs reais do MAPA, ANTT, CONAB e demais fontes. Nenhum dado real precisa ser publicado no GitHub.
3. Integrar vintage, balanços, consumo industrial e transportes com exemplos reais autorizados e reconciliação documentada.
4. Homologar por porto o parser HTML/PDF, o acesso autorizado, os dados observados e a frequência; Tubarão exige rota de acesso específica.
5. Implementar persistência, segurança, backup e interface somente após demonstração de dados íntegros.

Documentos: [guia de execução](docs/GUIA_DADOS_E_EXECUCAO.md), [plano de implementação](docs/PLANO_IMPLEMENTACAO.md), [decisões e gates](docs/DECISOES_E_GATES.md).

**Não houve deploy, contratação, coleta operacional real nem integração a serviços pagos.**

## Direitos do código

A visibilidade pública não constitui concessão automática de licença open-source. O projeto ainda não disponibiliza licença geral de reutilização. Código de terceiros só será incorporado após validação jurídica e técnica específica.

## Catálogo Mestre — Coletores e APIs do NIVON (19/10/2026)

Uma governança única conecta **57 fontes, 78 datasets, 15 grupos de dados, 16 frentes de inteligência e 120 indicadores previstos**. Esta contagem indica **escopo mapeado**, não coletores instalados ou homologados.

- Catálogo principal com fontes, modalidades, direitos, estágio e periodicidade proposta: [`config/fontes_nivon_master.v1.json`](config/fontes_nivon_master.v1.json).
- Matriz de produtos, indicadores, insumos e riscos de interpretação: [`config/matriz_produtos_indicadores.v1.json`](config/matriz_produtos_indicadores.v1.json).
- Guia operacional e gates de homologação: [`docs/ARQUITETURA_COLETORES_API.md`](docs/ARQUITETURA_COLETORES_API.md).
- Validadores offline: `src/nivon/catalogo_fontes.py`, `src/nivon/cobertura.py`, `src/nivon/orquestrador_fontes.py`.
- Adaptador inicial MDIC para CSV **exportação NCM/UF**: `src/nivon/mdic_exportacao.py`; arquivo oficial ainda não homologado. Dados municipais por SH4 estão em outro dataset.

Exemplos de inspeção sem rede, sem segredos ou custos:

```bash
PYTHONPATH=src python -m nivon.catalogo_fontes --resumo
PYTHONPATH=src python -m nivon.catalogo_fontes --produto DIESEL
PYTHONPATH=src python -m nivon.cobertura
PYTHONPATH=src python -m nivon.orquestrador_fontes --prioridade P0 --resumo
```

**Todos os novos datasets têm coleta, agendamento e redistribuição desabilitados.** O estado de `REAL_SNAPSHOT_TESTED` cobre somente as culturas com fixture real comprovada: soja e milho no parser CONAB, não algodão/trigo/sorgo. A fonte oficial e o estágio não constituem acesso contínuo, contrato comercial, backup ou go-live.

## Planejamento operacional dos 78 coletores e APIs — 19/10/2026

A organização técnica acrescentou um contrato de rota para **cada dataset catalogado**:

- `config/rotas_coleta.v1.json` — 78 rotas técnicas e bloqueios de acesso/execução. URLs são por **dataset** apenas quando fundamentadas; página institucional não é confundida com API pronta.
- `src/nivon/rotas_coleta.py` — validação cruzada 1:1 com o catálogo mestre, host oficial, direitos, histórico, restauração e ativação default-deny.
- `docs/PLANO_OPERACIONAL_COLETORES_API.md` — matriz dos 15 grupos, estratégia API/CSV/HTML/PDF/manual, prioridades P0–P2 e lacunas de escopo.
- `src/nivon/bcb_ptax.py` — parser OData PTAX com horas dos boletins, câmbio de compra/venda e data de publicação nula quando ausente. Ainda sem coleta real ou serviço agendado.

```sh
PYTHONPATH=src python -m nivon.rotas_coleta --resumo
PYTHONPATH=src python -m nivon.rotas_coleta --prioridade P0
```

Esses contratos **não ativam** nenhum dos 78 coletores; toda operação real depende dos gates de acesso, esquema, qualidade, histórico e persistência. O catálogo atual não dispensa a revisão de dados ainda faltantes, como armazenagem e comercialização de safras.
