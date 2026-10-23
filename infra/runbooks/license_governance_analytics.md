# NIVON — Direitos de bibliotecas ≠ direitos de dados

O módulo `src/nivon/infra_wheel_license_audit.py` inspeciona exclusivamente os arquivos `.dist-info/METADATA` dentro das wheels fixadas nos dois locks (AMD64 e ARM64), sem importar/executar o conteúdo das wheels, sem rede e sem copiar dados proprietários. Confirma hash de cada arquivo contra `infra/locks/analytics-*.json` antes de ler, limita o tamanho do METADATA e publica somente totais por tipo de declaração: SPDX, licença legada, classificador ou não identificada. Ausência ou corrupção de METADATA reprova o CI experimental.

**Interpretação obrigatória:** valores `License-Expression`, `License` e `Classifier` são declarações dos distribuidores, não decisão jurídica, revisão de NOTICE ou licença verificada. Mesmo se o código de Agrobr for MIT, não há evidência de direito de copiar ou republicar integralmente CEPEA, IMEA, CONAB ou fontes de terceiros; direitos de acesso, coleta, termos e comercialização devem ser tratados separadamente por fonte. O resultado mantém `source_data_rights_authorized=false`, `production_authorized=false`, `code_licenses_legally_reviewed=false`.

O script é executado no workflow multiarch já existente, somente após confirmação SHA-256 das 59 wheels. A medição é uma etapa para a auditoria completa das licenças, não homologa coletor nem substitui revisão especializada.
