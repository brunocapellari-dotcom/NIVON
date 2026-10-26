# Interface do coletor CEPEA/IMEA (offline, sem API oficial homologada)

Esta CLI reutiliza `importacao_cotacoes_autorizadas.py` e a quarentena
`historico_vintages.ArmazemVintages`. **Nao adquire dados, nao faz scraping
nem usa endpoint remoto.** O operador deve fornecer CSV licitamente obtido.

Exemplo de manifesto local, usando **dados sinteticos**:

```json
{
  "fonte_id": "IMEA",
  "fonte_url": "https://www.imea.com.br/",
  "edicao_id": "SINTETICA_20261021",
  "coletado_em": "2026-10-21T18:00:00Z",
  "publicado_em": null,
  "disponivel_em": null,
  "arquivo_csv": "cotacoes.csv"
}
```

Cabeçalho CSV exato: `serie_id;produto;localidade;competencia;referencia;preco;unidade`.
Competência mensal e referência diária; várias datas da mesma série em um mês
são aceitas com edição interna estável `edicao_id__REF_AAAAMMDD`. Duplicatas
da mesma série e data são rejeitadas. Não inventar horário de publicação.

Consulta segura, não escreve arquivo:
```bash
PYTHONPATH=src python -m nivon.cotacoes_csv_cli --manifesto manifesto.json
```

Somente se houver posse legal do arquivo e decisão de armazenar **quarentena local**:
```bash
PYTHONPATH=src python -m nivon.cotacoes_csv_cli --manifesto manifesto.json --persistir-quarentena --banco quarentena.sqlite
```

Ambos os modos imprimem apenas metadados de integridade, sem preços.
A segunda opção armazena linhas já normalizadas, não os bytes brutos. O lote é
atômico no SQLite: qualquer conflito ou falha reverte todas as novas linhas. Para auditoria operacional futura, preservar original RAW fora do banco,
prova de direitos, evidência independente de publicação, backup e restauração.
Dados de quarentena jamais são publicados, enviados ao briefing ou usados em
backtest temporal. A entrada manual de datas/URL não valida automaticamente
os direitos nem a fonte.
