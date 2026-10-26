---
name: nivon-coleta-qualidade
description: Auditar uma coleta real do NIVON, preservar provenance e impedir dados não validados em relatórios.
---
# Coleta e qualidade NIVON
1. Verifique o coletor existente, fonte primária, última competência, data de publicação e extração; não crie coletor substituto sem evidência de falha.
2. Confira licenciamento, formato, unidades, cobertura geográfica, safra versus ano civil, duplicatas e datas.
3. Se houver lacuna de API, avalie Firecrawl/Magnitude **somente após aprovação do domínio, custo e acesso**; não retorne dado extraído como OBSERVADO sem validação.
4. Preserve dados originais no pipeline existente e gere registro de proveniência. Nunca insira zeros nos dados ausentes.
5. Entregue resultado verificável, teste, origem e indicação clara do que permanece bloqueado. Não modifique produção sem autorização.
