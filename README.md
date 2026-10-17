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
- `src/nivon/ingestao.py` — CSV local com limites, cabeçalho, hash SHA-256, datas, delimitação e codificação explícitas.
- `src/nivon/importadores.py` — mapeamento exato do layout de cada publicação, sem supor cabeçalhos reais da ANTT/MAPA. Exige domínios conhecidos de fábrica e carga própria.
- `src/nivon/destinos.py` — regiões com fábricas MAPA × terminais × destinos ANTT, NCM amostral, recorrência mensal e rejeição de recortes mensais duplicados.
- `src/nivon/analise_local.py` — execução offline completa a partir de CSVs e configuração autorizados.
- `src/nivon/portos.py` — cadastro canônico inicial de dez portos e contagem prudente de escalas; IMO sozinho não representa uma escala.
- `src/nivon/lineup_html.py` — leitura offline de HTML tabular previamente salvo, com mapeamento de cabeçalhos e estado exclusivamente PROGRAMADO.
- `src/nivon/coleta_web.py` — aquisição HTTPS bloqueada por padrão, com allowlist de host, sem redirects, MIME, tamanho e hash. **Não habilitada nem testada com fontes reais.**

`config/portos_brasil.v1.json` é catálogo, não declaração de que os dez portos estejam operacionais. Nenhum conector portuário está homologado.

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

**92 casos de testes definidos em nove arquivos**. A execução integral no commit mais recente ainda **não tem evidência confirmada de CI ou execução local**; a contagem não equivale a testes aprovados.

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
