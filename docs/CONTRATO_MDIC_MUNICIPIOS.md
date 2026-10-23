# MDIC Comex Stat — municípios fiscais por SH4 (offline)

Layout primário oficial, atualizado em 06/10/2026:
https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta

Contrato: \`CO_ANO;CO_MES;SH4;CO_PAIS;SG_UF_MUN;CO_MUN;KG_LIQUIDO;VL_FOB\`.

O adaptador \`src/nivon/mdic_municipios.py\` lê CSV municipal UTF-8 local com limite de tamanho/linhas, hash da edição e validação estrita de schema, mês, SH4, código do município declarado, país, quilogramas e valor FOB. Aceita parâmetro de operação IMPORTACAO ou EXPORTACAO sem misturar sinais. Agrupa somente recortes fiscal/SH4/país/período.

**Risco de interpretação crítico:** SG_UF_MUN e CO_MUN são UF e município de domicílio fiscal da empresa declaradora. NÃO são origem agrícola, local de embarque, terminal, destino logístico ou município produtor. SH4 NÃO é NCM de oito dígitos. Código de município fica não validado até cruzamento com tabela histórica MDIC/IBGE; código 7 dígitos não garante vigência do município na safra histórica.

Este módulo não busca, distribui ou ativa a base. Faltam: amostra real de importação/exportação e totais oficiais de controle, direitos por operação, validação de tabela de códigos histórica, armazenamento versionado e confirmação de regime de publicação.

Teste: \`PYTHONPATH=src python -m unittest discover -s tests -v\`.
