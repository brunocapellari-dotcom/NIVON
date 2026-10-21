# NIVON — ANP: preço semanal municipal diesel, 20/10/2026

**Natureza:** implementação de coleta/ETL offline e briefing condicionado; NÃO está homologada em produção.

## Fonte original verificada em pesquisa

- Série histórica oficial por município, XLSX 2026:
  https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/semanal-municipios-2026.xlsx/view
  - A página identificava arquivo de aproximadamente 8 MB, última modificação 09/10/2026.
  - NÃO foi possível baixar o binário original para homologar layout/semana atual.
- Lista oficial de pesquisas semanais e arquivos LPC:
  https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas
- Informações metodológicas:
  https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/informacoes-levantamento-de-precos-de-combustiveis
  - Preço municipal: média aritmética simples dos postos pesquisados;
    NÃO é preço ponderado por litros vendidos.
- Referência técnica complementar de estrutura da aba MUNICIPIOS:
  https://github.com/AlexandreZanata/brazil-fuel-prices-app/blob/main/docs/data-sources.md
  - Layout candidato: linha 7, aba MUNICIPIOS, DATA INICIAL, DATA FINAL,
    ESTADO, MUNICÍPIO, PRODUTO, NÚMERO DE POSTOS PESQUISADOS,
    UNIDADE DE MEDIDA, PREÇO MÉDIO REVENDA.
  - Essa referência de terceiros NÃO substitui teste do XLSX oficial.

## Módulos implementados

- `anp_indice_lpc.py`: identifica links oficiais RESUMO_SEMANAL a partir do HTML já recebido;
  não inventa URL da semana, não consulta rede, não confunde arquivo de revendas individuais.
- `anp_resumo_lpc.py`: leitor XLSX limitado e em modo read-only, separa
  diesel comum de S10, normaliza o nome completo do estado para UF,
  valida semana de sete dias, preço, unidade e número amostral de postos.
  Retorna observações apenas de municípios efetivamente pesquisados em MT.
- `anp_diesel_briefing.py`: só constrói indicadores após validação do XLSX,
  versão SHA, licença comprovada, autorização de coleta/armazenamento/publicação,
  data de disponibilização e limite de defasagem; não cria preços fictícios.
- `pipeline_briefing.py`: aceita opcionalmente resumos ANP homologados para a seção DIESEL,
  sem alterar cotações CME/ICE ou fretes anunciados.
- `scripts/inspecionar_lpc_semanal.py`: CLI de inspeção offline; lê XLSX local
  autorizado e grava JSON com município, tipo, período, número de postos e média amostral.

## Executar inspeção offline

```sh
python -m pip install -e '.[excel]'
PYTHONPATH=src python scripts/inspecionar_lpc_semanal.py \
  --arquivo /dados/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx \
  --url-fonte 'https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc/2026/resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx' \
  --coletado-em 2026-10-20T10:00:00-03:00 \
  --saida /dados/anp_diesel_mt.json
```

Arquivos acima são EXEMPLOS de nomes/competências, não declaração de que o
download foi realizado. Os diretórios devem existir; não há chamada de rede.
A saída marca `publicavel=false`.

## Gatilhos para operação

1. Confirmar URL individual no índice oficial e baixar legalmente o XLSX real de pelo menos 3 semanas.
2. Conferir a aba e cabeçalho, unidade, semana e preço em comparação com a tabela pública ANP.
3. Registrar termos de uso/redistribuição, data de disponibilização e hash de cada vintage.
4. Configurar reexecução incremental, hash de alteração e armazenamento durável com restauração testada.
5. Habilitar o campo `ANP_PRECO_REVENDA_DIESEL` apenas após evidências e autorização.
6. Sem dados novos, marcar dado ausente/desatualizado, NÃO repetir cotação antiga como atual.

**Não confundir:**
- preço diesel S10 de revenda (diesel B) com diesel A refinaria, paridade internacional ou preço da transportadora;
- série semanal MUNICIPAL ANP com a agregação inferida de microdados CSV mensais;
- ausência de município pesquisado com preço zero;
- médias de diesel municipal (ANP) com média de **frete** por município, proibida na governança do NIVON.
