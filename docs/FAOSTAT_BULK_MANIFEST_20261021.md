# NIVON — FAOSTAT bulk manifest: acesso público alternativo (21/10/2026)

A API REST legado `fenixservices.fao.org/faostat/api/v1/en/data/QCL` excedeu o timeout de 20 segundos no runner de homologação HTTP da PR #107. O dado **não foi comprovado indisponível**, apenas a consulta desse ambiente falhou.

Foi identificado e implementado o catálogo **primário oficial** `https://bulks-faostat.fao.org/production/datasets_E.json`. Esse JSON divulga nome, domínio FAOSTAT, data de atualização da fonte, formato ZIP CSV, volume de registros, tamanho e a URL oficial por conjunto.

O módulo `src/nivon/faostat_bulk_manifest.py` valida o catálogo, garante a presença de `QCL`, limita a resposta a 1.5MB, acessa uma só URL HTTPS de confiança, não redireciona, registra SHA e data/hora da coleta. As URLs presentes dentro do JSON são **referências** e jamais acessadas automaticamente. Os domínios prioritários são QCL (produção), RFB (fertilizantes), RFM (matriz de comércio de fertilizantes), PP (preços ao produtor), BE (bioenergia), TCL (comércio agrícola) e TCLI (indicadores).

Volume ilustrativo documentado no manifest oficial: QCL possui cerca de 33 MB ZIP comprimido e 4,2 milhões de registros. **Essa PR não baixa nenhum arquivo histórico ZIP, não carrega dados em banco, não ativa cron e não contrata infraestrutura**.

Novo dataset `FAO_FAOSTAT_BULK_CATALOGO` coexiste com `FAO_FAOSTAT_LONG_RUN`, sem declarar que o catálogo equivale ao dado de produção. O próximo passo depende de implementar leitura seletiva de ZIP, validação dos códigos FAO e persistência idempotente com revisões, depois de acesso real testado.

Docs: https://www.fao.org/faostat/en/ e https://bulks-faostat.fao.org/production/datasets_E.json
