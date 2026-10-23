# NIVON — Histórico acumulado por fonte e próximos portões

**Data:** 23/10/2026. **PR:** #215 (base #187). **Estado:** CODE_TESTED_SYNTHETIC_ONLY / SOURCE_RIGHTS_NOT_VERIFIED / RELEASE_BLOCKED.

## Implementado

1. O relatório de prontidão não reinicia a contagem a cada execução: junta registros SQLite anteriores e PDFs do lote atual, sem duplicar replay do mesmo instante.
2. O método `history_asof` só permite revisões sobre documentos publicados e coletados antes do corte. `audit_history_asof` inclui arquivos armazenados com publicação **desconhecida** apenas para auditoria de lacunas, sem vazamento para modelos ou indicadores históricos.
3. São exibidos `population_basis=PERSISTED_AUDIT_HISTORY_PLUS_CURRENT_BATCH`, `documents_in_current_batch`, `persisted_audit_editions_prior_to_batch`, hashes/horários distintos e todos os bloqueios editoriais.
4. Validação completa é anterior ao commit transacional. A nova leitura paginada por chave temporal suporta até 2.000 edições por fonte/série, com páginas de 100 por padrão, quota de 48 MB de payload JSON e erro explícito ao ultrapassar cotas. As APIs antigas de leitura limitada seguem disponíveis para compatibilidade.
5. O teste real de contêiner em CI agora percorre cinco execuções sem rede: primeiro lote de 3 PDFs sintéticos (2 Paranaguá, 1 Itaqui), dry-run, commit e replay; segundo lote separado com 3ª edição Paranaguá, commit e replay. Resultado: 4 edições SQLite, 2 revisões documentais de ETA, 3 edições distintas Paranaguá. Nenhuma atracação/carga realizada inferida, release sempre bloqueado.

## Fontes oficiais identificadas em pesquisa pública — SOMENTE CANDIDATAS

| Fonte | Endereço | Advertência |
|---|---|---|
| Paranaguá, corredor oeste 22/10/2026 | https://www.portosdoparana.pr.gov.br/Arquivo/LINE-CORREDOR-OESTE-22102026 | Página referencia LINEUP22102026.pdf, mas mostra carimbo genérico 04/10/2023. Esse carimbo NÃO comprova quando o PDF foi publicado |
| Paranaguá, edição 31/08/2026 | https://www.portosdoparana.pr.gov.br/Arquivo/LINE-CORREDOR-OESTE-31082026 | Candidato a comparação de layouts, não a prova de licença ou integridade dos bytes |
| Itaqui, programação 15/11/2025 | https://www.portodoitaqui.com/public/_files/arquivos/MAPA%20DE%20ATRACA%C3%87%C3%83O%20-%2015%2011%202025%20-15h00%20-%20clientess_6918e1c65c216.pdf | Material histórico indexado, com estados ATRACADO/FUNDEADO/ESPERADO, não uma edição atual nem prova de embarque realizado |

**Importante:** estas páginas foram identificadas por pesquisa, não são PDFs baixados, autenticados ou licenciados para coleta. URL pública não garante direitos de retenção, análise e redistribuição. Os endereços acima não são habilitados por esta PR como coletores automáticos.

## Bloqueios externos e próximos itens

- Confirmar direitos por operação com a autoridade e obter por meios autorizados ao menos três PDFs originais independentes por fonte/série, com URL exata, hash dos bytes, página, publicação efetiva, data de referência, coleta e competência.
- Revisar visualmente a extração, incluindo fuso, status do navio, múltiplas linhas de produto e revisão de layout. Se faltarem DUVs, preservar a camada de programação sem transformar Nº Prog em visita comprovada.
- A paginação do histórico foi implementada e exercitada com 205 edições anteriores mais 1 nova; para operação superior a 2.000 edições por fonte/série, planejar armazenamento analítico com paginação de relatórios e redução incremental de memória, sem ignorar arquivos em silêncio.
- Após direitos e amostras reais verificados, conduzir aceite shadow e aprovação humana antes de qualquer implantação, cron, serviço pago ou publicação.

**Nunca inferir** volume embarcado, partida ou atracação com base somente no line-up. Mesmo com três documentos sintéticos distintos, release_allowed continua false.
