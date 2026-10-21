# NIVON — Parser offline XLSX do progresso semanal CONAB (21/10/2026)

## Origem e escopo da referência

- Portal primário: https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra
- Referência de documentação/estrutura: projeto público `bruno-portfolio/agrobr`, especialmente `docs/api/conab_progresso.md`, `agrobr/conab/progresso/parser.py` e `models.py` (código agrobr MIT, sujeito a termos próprios dos dados).
- Fixture incluída como **representação Base64 inalterada do conteúdo binário de terceiro**, proveniente de `tests/golden_data/conab_progresso/progresso_sample/response.xlsx`, blob GitHub `05d50fb46c23186ec8cee23f1969746acec082e4`, metadado de captura do terceiro `2026-02-24T09:59:00Z`. O README/contrato público de `agrobr` declara 11 observações, semana de `2026-02-07` e soja colheita MT = `0.468`. **Não foi conferida a cadeia de aquisição oficial nem autenticidade histórica do arquivo junto à CONAB.**
- A CONAB indica publicação semanal de progresso de safra por cultura e UF. A URL e o timestamp de publicação são entradas externas; não são extraídos/verificados pelo próprio XLSX.
- Manter atribuição CONAB + agrobr e não redistribuir dados derivados fora do escopo permitido, pendente auditoria específica da licença individual do XLSX.

## Implementação

`src/nivon/conab_replay_xlsx.py` interpreta com Python stdlib apenas o subconjunto OOXML conhecido, sem HTTP nem dependências opcionais. Segurança: limite de bytes/células/linhas, bloqueio de caminho ZIP/ZIP-bomb, macros, referências externas, fórmulas não avaliadas, abas ambíguas, células de erro, percentuais fora de fração, pares de datas incompletos, chaves repetidas e publicação posterior à captura.

- Reconhece cabeçalhos de cultura e safra, operação Semeadura/Colheita, sequência de três datas da semana, estados da tabela de localidades, nota de cobertura e `N estados` como `MEDIA_ESTADOS`.
- Mantém `MEDIA_ESTADOS` separado de `BR`. Brasil por soma/média não pode ser inferido; se a planilha trouxer uma linha BR requer contrato especializado.
- Extrai `pct_ano_anterior`, `pct_semana_anterior`, `pct_semana_atual`, `pct_media_5_anos`, `revisado`, `n_estados`, `cobertura_area_pct`; não cria percentual zero a partir de células vazias.
- Normaliza por `nivon.conab_agrobr.normalizar_progresso` e serializa no mesmo contrato do ledger CONAB.
- `preflight_migracao_conab.py` aceita execução de XLSX somente quando `parser_versao=NIVON_PROGRESSO_XLSX_OOXML_V1` e MIME de XLSX, confrontando bytes atuais e dados reextraídos com JSON informado e legado, **sem gravar em SQLite**.

## Gates e distinção de evidências

Teste de golden de terceiro = evidência do comportamento do parser em um arquivo de referência, não teste de autenticidade, direitos ou proveniência. Parser não prova fonte do download. Se o XLSX alterar layout/fórmulas/abas, falha fechado. A padronização de `semana` não equivale a comprovação de horário de publicação.

O relatório conserva `migracao_permitida=false`, `parser_conab_oficial_homologado=false` e `direitos_validados_externamente=false`. Não ativar coleta, cron, lançamento de dado ou relatório externo.

## Próximos passos antes da migração

1. Obter XLSX original diretamente da URL publicada pela CONAB, de maneira lícita e autorizada, registrando URL final, `ETag`/`Last-Modified` quando presentes, timestamp de obtenção e SHA bruto.
2. Comparar saída do parser com arquivo oficial preservado e com série de edições de layouts diferentes, com auditoria de linhas ignoradas e percentuais em diferentes formatos.
3. Registrar licença individual, restrições de distribuição, direitos por operação e atribuição.
4. Integrar os dois registros com provas bitemporais, backups/restore, prova do parser por hash de código e teste de migração idempotente em cópias privadas.
5. Somente após avaliação independente permitir migração real e publicação.
