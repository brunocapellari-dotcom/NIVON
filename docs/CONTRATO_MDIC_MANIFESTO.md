# MDIC — descoberta de histórico anual sem baixar massa de dados

Página oficial de dados abertos: https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta.

**Verificação pública pontual em 19/10/2026** (GitHub Actions, somente índice HTML, sem CSV): 167 links de arquivo apontaram para `balanca.mdic.gov.br`; as oito amostras de 2025–2026 confirmaram quatro recursos anuais: `/balanca/bd/comexstat-bd/ncm/EXP_AAAA.csv`, `IMP_AAAA.csv`, `/balanca/bd/comexstat-bd/mun/EXP_AAAA_MUN.csv` e `IMP_AAAA_MUN.csv`.

O resolvedor `src/nivon/mdic_manifesto.py` usa HTML oficial recebido localmente para **extrair links realmente publicados**, nunca fabricar endereços para anos não observados. Suporta 1997 ao ano atual; cruza 4 tipos por período, rejeita duplicação, link externo, caminho incompatível, ano faltante e arquivo consolidado extinto. Quando é permitida saída parcial, produz `ausentes` explicitamente. O `sha256_html` documenta o índice; **não** substitui o hash do CSV do ano. A seleção incremental apenas marca arquivos candidatos, sem baixar dados.

A Secex descontinuou `EXP_COMPLETA.zip`, `IMP_COMPLETA.zip`, `EXP_COMPLETA_MUN.zip`, `IMP_COMPLETA_MUN.zip` em junho de 2025 e recomenda baixar o histórico uma vez, revalidando o ano mais recente. A base histórica 1989–1996 usa NBM, **não NCM**, com layout próprio ainda não implementado. Os dados da base municipal são SH4 por domicílio fiscal do exportador/importador, **não município de embarque**.

A implementação não agenda, não publica, não usa direitos de terceiros, não baixa CSV, não cria serviço pago. Faltam direitos de coleta/armazenamento/publicação, teste de bytes reais, totais oficiais, dicionário NCM/SH4 com vigência, consulta incremental de hashes e persistência com backup.
