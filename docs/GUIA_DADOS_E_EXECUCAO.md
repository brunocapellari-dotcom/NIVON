# Procedimento local de entrada de dados — NIVON v0.2

A execução usa arquivos já obtidos pelo operador por meios autorizados. **Nenhum coletor real foi habilitado**. Contratos sintéticos não comprovam compatibilidade com a edição efetiva dos arquivos da ANTT ou do SIPEAGRO.

## Reproduzir sem baixar nada

Python 3.11+ no diretório raiz do repositório:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon.analise_local --config config/contrato_exemplo_sintetico.json
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m nivon.analise_local --config config/contrato_exemplo_sintetico.json
```

As duas bases em `tests/fixtures/` são **inventadas integralmente** para testes. Não são dados publicados pelo MAPA ou pela ANTT. O exemplo deve produzir 600 toneladas identificadas em uma rota AMBÍGUA e registrar 50 toneladas de NCM ausente. Isso comprova apenas o funcionamento esperado da lógica com a fixture.

## Preparar um arquivo real sem publicá-lo

1. Verificar a origem e a licença **da operação específica** e registrar a edição. Não usar endpoint interno Power BI como API homologada.
2. Obter o CSV por meio autorizado e armazená-lo fora do Git. A pasta `dados/` é ignorada por padrão.
3. Inspecionar o cabeçalho e o conteúdo do CSV. Preencher os nomes exatos das colunas em `colunas`; **não** presumir que os nomes da fixture coincidam com os oficiais.
4. Para MAPA, preencher também os domínios confirmados de situação, atividade e área. Um status desconhecido deve interromper o processamento.
5. Para ANTT, identificar a unidade da coluna de volume, NCM de oito dígitos, mês de referência, carga própria e terceiros. O importador atual requer **toneladas** com decimal pt-BR. Se o arquivo tiver outra unidade, deve haver adaptador e teste explícitos, jamais conversão implícita.
6. Identificar terminais por município/UF e produto com documentação de referência; a presença simultânea de terminal e fabricante produz `AMBIGUO`.
7. Atualizar `status` e `operacoes` somente quando a fonte estiver permitida para leitura local. A declaração no JSON é um **registro operacional do operador**, não substitui termos do titular.
8. Executar somente localmente. Não versionar os arquivos reais, o JSON com caminhos privados, nem informações comerciais restritas.
9. Conferir os totais e as proporções publicadas na fonte; não publicar como CONSUMO_REAL um indicador de MOVIMENTACAO_AMOSTRAL_IDENTIFICADA_NCM.

## Limitações deliberadas

- Não há cliente HTTP, scraping ou streaming ativado.
- Arquivos CSV usam delimitador `;` ou `,` e codificação explícita (`utf-8-sig`, `utf-8` ou `cp1252`).
- O recorte NCM reconhece apenas milho comercial (10059010) e soja comercial (12019000), evitando confusão com sementes. Classificações futuras exigem tabelas equivalentes auditadas.
- NCM ausente preserva o volume apenas na categoria SEM_NCM; nunca vira automaticamente soja/milho.
- Entradas mensais são **agregações únicas** por mês, rota, produto e tipo de frota: duplicatas falham em vez de dobrar o volume. Revisões passam por seleção de vintage temporal antes do uso.
- Recorrência = ao menos três meses distintos de movimentação no horizonte-padrão de doze meses; é uma métrica descritiva, não confirmação de destinatário.
- O cadastro MAPA indica estabelecimentos, não capacidade, consumo ou fabricante efetivo de ração de aves/suínos quando a categoria não estiver especificada.
- Não existe extrapolação automática para o volume total que falta no recorte NCM.
- Os coletores de portos não estão ativados. `lineup_html.py` processa apenas HTML já salvo e exige mapeamento específico; não confirma operação física.

## Fontes de referência verificadas documentalmente

- MAPA/SIPEAGRO — Alimentação Animal: https://dados.agricultura.gov.br/dataset/sipeagro/resource/378b184b-67bd-48fa-9901-17bb7a0700fb
- CSV do recurso MAPA: https://dados.agricultura.gov.br/dataset/52a01565-72d6-410e-b21b-64035831a7be/resource/378b184b-67bd-48fa-9901-17bb7a0700fb/download/sipeagroalimentacaoanimal.csv
- ANTT — painel e conceitos: https://www.gov.br/antt/pt-br/assuntos/cargas/dadostrc/movimentacao-de-cargas
- ANP — dados abertos de biocombustíveis: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/arquivos-producao-de-biocombustiveis

As páginas dessas fontes **não substituem uma amostra de CSV real com schema, direitos e teste de reconciliação**.
