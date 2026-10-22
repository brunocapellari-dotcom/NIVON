# NIVON — Auditoria multivintage offline da CONAB (21/10/2026)

## O que foi encontrado

O repositório público [bruno-portfolio/agrobr](https://github.com/bruno-portfolio/agrobr) contém **três referências XLSX adicionais**, além da fixture pequena de fevereiro usada na PR #70. Para as três referências, os arquivos e os hashes estão documentados no repositório do terceiro; nenhum deles foi adquirido diretamente da CONAB pelo NIVON.

| Competência do XLSX | Caminho no agrobr | Bytes | SHA-256 publicado |
| --- | --- | ---: | --- |
| 27/09/2025 | `tests/golden_data/conab_progresso/historico_20250927/response.xlsx` | 78.617 | `ae5932cbef54b2b141b8b45adc1e66c6ff091104725989438f6583ff4fa5e050` |
| 21/02/2026 | `tests/golden_data/conab_progresso/oficial_20260925/progresso_20260222.xlsx` | 76.946 | `d42d49715bb393c14f67855db7af2e79d08a3bd982201e7a0ce02f75e2ec8ff9` |
| 18/09/2026 | `tests/golden_data/conab_progresso/oficial_20260925/progresso_20260920.xlsx` | 77.631 | `35dd6b33daa9d04e9797cb25109722fa338cd85d5fdca3600bf3246bed94376e` |

Fontes dos metadados:
- [Oráculo independente setembro/2025](https://github.com/bruno-portfolio/agrobr/blob/main/tests/golden_data/conab_progresso/historico_20250927/expected.json): 66 registros, sete culturas, amostras de células e revisão marcada com `*`.
- [Metadados de captura reportados pelo terceiro — setembro/2025](https://github.com/bruno-portfolio/agrobr/blob/main/tests/golden_data/conab_progresso/historico_20250927/metadata.json).
- [Manifesto reportado pelo terceiro — fevereiro e setembro/2026](https://github.com/bruno-portfolio/agrobr/blob/main/tests/golden_data/conab_progresso/oficial_20260925/manifest.json).

**Esses metadados foram conferidos nos arquivos de referência do GitHub; a validade da cadeia original de download, autorização individual do documento e autenticidade do produtor de dados ainda não foram auditadas.**

## Código novo

- `config/conab_referencias_multivintage_20261021.json`: catálogo com ID da referência, origem no GitHub, SHA do blob Git, **SHA-256 dos bytes publicado pelo terceiro**, tamanho, competência, URL oficial declarada, timestamp de coleta declarado e oráculo conhecido. A presença de SHA não é a comprovação de posse dos bytes.
- `src/nivon/auditoria_vintages_conab.py`: validação **offline**. Verifica arquivos XLSX disponibilizados previamente na pasta indicada; confere SHA-256 e tamanho, executa o parser OOXML do NIVON, compara semana observada, contagem e culturas quando houver oráculo. Recusa arquivos desconhecidos, symlinks, nomes perigosos, SHA divergente e duplicidade.
- `tests/test_auditoria_vintages_conab.py`: testes de contrato e falha fechada usando **somente a fixture pequena já versionada na PR #70**, não os três arquivos históricos adicionais.
- **Nenhum arquivo XLSX adicional é gravado no repositório.** Isso evita replicar anexos cuja licença individual ainda requer revisão.

## Execução offline (sem downloads automáticos)

Primeiro, disponibilizar os três arquivos de terceiro em uma pasta de trabalho com autorização apropriada, usando os nomes exatos do catálogo. Depois:

```sh
PYTHONPATH=src python -m nivon.auditoria_vintages_conab \
  --catalogo config/conab_referencias_multivintage_20261021.json \
  --diretorio /caminho/absoluto/arquivos-locais --resumo
```

Se o diretório estiver vazio, o relatório exibirá **três edições pendentes**, zero reprocessadas e `parser_multivintage_testado_localmente=false`. **Não representa sucesso de testes sobre planilhas não fornecidas.**

Se arquivos forem fornecidos, qualquer problema de hash ou layout falha a execução. Duas vintages efetivamente lidas e aprovadas permitem marcar `parser_multivintage_testado_localmente=true` — indicador somente do parser, **não de origem ou direitos**.

## Riscos e próximas ações

1. **Obter os corpos binários do portal CONAB** por meio permitido em um ambiente com HTTPS/DNS operacionais, preservar metadados e SHA do arquivo efetivamente capturado; não confundir bytes do terceiro com captura própria.
2. Verificar licença individual do XLSX antes de persistir, transformar, compartilhar ou publicar conteúdo.
3. Executar a auditoria multivintage com pelo menos duas edições reais; resolver quebras de layout, diferenças de competência, oráculos (inclusive revisões e cobertura) e corrigir parser com testes.
4. Conferir captura → armazenamento privado → revalidação posterior → auditoria de vigência e rights; manter backups.
5. Ativação/migração/publicação **dependem de autorização e auditoria adicionais**.

Estados incondicionais em todos os relatórios desta PR: `captura_proveniencia_oficial_comprovada=false`, `licencas_confirmadas_individualmente=false`, `migracao_permitida=false` e `publicacao_permitida=false`. Nenhuma coleta automática, gasto, banco ou workflow externo é acionado.
