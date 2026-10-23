# MDIC — qualidade e conferência de totais de comércio exterior

A página oficial https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta disponibiliza links **Totais para validação** por exportação/importação e por NCM/município-SH4. Não se deve equiparar total municipal de domicílio fiscal a volume portuário ou operacional.

`mdic_reconciliacao.reconciliar_totais_mdic` verifica em separado a soma de linhas de todo o CSV, meses presentes (não inventar meses com zeros), kg e FOB USD do arquivo completo, contra **referências mensais explicitamente fornecidas pelo operador**. Tolerâncias em unidades inteiras configuráveis, máximas de 1.000 kg/USD, exigem revisão metodológica antes de serem adotadas. Parâmetros de referência devem ser derivados dos arquivos oficiais de validação no mesmo vintage e período; esta conferência não faz download, não determina legitimidade por confiar na string da URL e não homologa dados automaticamente.

`fonte_referencia_comprovada_por_terceiro=False`, `base_historica_homologada=False` e `publicacao_comercial_autorizada=False` permanecem fixos. Próximos passos são implementar leitor do layout real de *Totais para validação*, versionar referência e resultados com SHA, tratar revisões históricas e validar um arquivo anual inteiro autorizado.

Execução sintética via `PYTHONPATH=src python -m unittest discover -s tests`. Sem rede, sem deploy e sem agendamento.
