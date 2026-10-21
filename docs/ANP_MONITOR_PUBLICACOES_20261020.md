# NIVON — ANP diesel: monitor de atualização e homologação da série municipal

Data de referência: **20/10/2026**. Componente de dados, não canal de envio.
Nenhum endpoint, tarifa, coleta automática ou republicação foi ativado.

## Evidências institucionais observadas

1. ANP, últimas pesquisas semanais:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas

   - Indica a semana **11 a 17/10/2026**, com link para preços médios de Brasil,
     regiões, estados e municípios e planilha por posto revendedor;
   - a página listava atualização em **20/10/2026, 13h05**, mas essa data é
     **metadado da página** — não a data de publicação de cada preço municipal.

2. ANP, série histórica municipal do ano de 2026:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/semanal-municipios-2026.xlsx/view

   - Página do arquivo indicava edição em **20/10/2026, 14h34**.
   - O conteúdo XLSX **não foi baixado com sucesso neste ambiente**; portanto
     aba, colunas, data real da última linha, hash dos bytes, tipo de diesel e
     municípios cobertos **não foram homologados com arquivo real**.

## Status técnico verificável

- Existem leitores distintos para planilha semanal consolidada por município,
  série anual municipal e arquivo granular de postos; nenhum substitui outro
  automaticamente.
- `anp_indice_lpc.py` identifica URLs do arquivo semanal **que realmente
  apareçam como links no HTML autorizado**, sem construir URL fictícia.
- `anp_monitor_atualizacao.py` compara índice semanal, competências anteriores
  e metadados da página anual. Alertas:
  `SEM_SEMANA_LOCALIZADA_NO_INDICE`,
  `INDICE_SEMANAL_DEFASADO`,
  `SEMANAS_ANTES_PRESENTES_REMOVIDAS_DO_INDICE`,
  `HTML_ALTERADO_SEM_NOVA_SEMANA_VERIFICADA` e
  `PAGINA_ANUAL_ATUALIZADA_NAO_PROVA_DADOS_DA_SEMANA`.
- `scripts/auditar_atualizacao_anp.py` roda **offline**, a partir de um HTML
  previamente obtido licitamente, gravando JSON por escrita atômica.
- Os dados atuais não podem ser publicados até homologação de licença,
  layout e PDF/XLSX real, além de conferência da semana e do produto.

## Comando para auditar uma captura autorizada

```bash
PYTHONPATH=src python scripts/auditar_atualizacao_anp.py \
  --indice-html /dados/autorizados/anp_indice.html \
  --indice-coletado-em 2026-10-20T15:00:00-03:00 \
  --gerado-em 2026-10-20T16:00:00-03:00 \
  --saida /dados/auditoria_anp.json
```

Comparação com auditoria anterior:

```bash
PYTHONPATH=src python scripts/auditar_atualizacao_anp.py \
  --indice-html /dados/autorizados/anp_indice_novo.html \
  --indice-coletado-em 2026-10-20T15:00:00-03:00 \
  --gerado-em 2026-10-20T16:00:00-03:00 \
  --anterior /dados/auditoria_anp_anterior.json \
  --saida /dados/auditoria_anp_nova.json
```

`--anual-meta` aceita somente metadados observados da página de 2026 com
`pagina_url`, `pagina_atualizada_em`, `pagina_coletada_em`,
`html_sha256`, `arquivo_baixado=false` e `schema_homologado=false`.
É deliberadamente impossível declarar download/validação de planilha por essa rota.

## Próximos bloqueios para ingressar em produção

- Localizar e obter **o XLSX efetivo**, por acesso permitido, em duas ou mais
  revisões diferentes; não contornar WAF, CAPTCHA ou restrição de acesso.
- Conferir aba, cabeçalho, todas as unidades, município e produto usando
  `openpyxl`, com hash dos bytes e proveniência explícita.
- Verificar os termos de uso e condições de republicação derivados de
  indicadores públicos; termo de acesso público não constitui licença presumida.
- Conciliar a planilha semanal recente com o histórico anual 2026 em
  semana/município/produto, **sem fazer média entre municípios** ou
  transformar preço amostral de revenda em PPI/preço negociado.
- Habilitar coleta e publicar somente após homologação auditável. Se não houver
  linha para determinado município, mostrar `DADO_INDISPONIVEL`, não zero.

Este é um mecanismo de **descoberta e controle de fontes**, não alegação de
coletores ativos, preços apurados ou série atual validada.
