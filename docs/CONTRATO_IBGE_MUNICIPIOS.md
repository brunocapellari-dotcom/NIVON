# NIVON — IBGE Municípios: contrato offline (19/10/2026)

- Dataset canônico: \`IBGE_CODIGOS_MUNICIPIOS\`; documentação oficial: https://servicodados.ibge.gov.br/api/docs/localidades.
- Endpoint documentado de consulta: https://servicodados.ibge.gov.br/api/v1/localidades/municipios; **não executado neste incremento**.
- \`src/nivon/ibge_municipios.py\` valida JSON local e identifica municípios por código IBGE de sete dígitos, nome, UF e hash SHA-256 do payload. Rejeita duplicatas, UFs conflitantes, campos inválidos e datas de coleta sem timezone.
- O uso de nome normalizado só resolve correspondência inequívoca. Municípios homônimos entre estados exigem UF; aliases históricos e municípios extintos não são inferidos.
- A API não disponibiliza necessariamente data de publicação, competência ou início/fim de vigência. Esses campos permanecem \`null\`; a coleta **não substitui** a publicação e o snapshot atual não deve reescrever períodos históricos.
- Este adaptador **não habilita** coleta, agendamento, redistribuição ou publicação comercial. Mantêm-se os gates de direitos por operação, amostra real, reconciliação nacional, histórico bitemporal, persistência durável e recuperação.
- \`tests/test_ibge_municipios.py\` cobre tanto hierarquias antigas quanto novas e casos adversariais, com dados 100% sintéticos. Rodar \`PYTHONPATH=src python -m unittest discover -s tests -v\`.

Regra de implantação: ativar somente após aprovação separada da fonte/uso e teste de snapshot real autorizado. NUNCA publicar nomes aproximados como se fossem códigos municipais confirmados.
