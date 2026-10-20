# NIVON — descoberta histórica CONAB Progresso Semanal

Data-base: 20/10/2026. Estado: **código offline, sem coleta automática de dados reais**.

## Escopo e recuperação de componentes

A fonte canônica é CONAB_PROGRESSO_SEMANAL, já presente em config/fontes_nivon_master.v1.json e config/rotas_coleta.v1.json. O normalizador conab_agrobr.py transforma percentuais por cultura/UF. progresso_conab_historico.py conserva snapshots em SQLite. Ambos são preservados.

O incremento adiciona o parser offline src/nivon/conab_progresso_indice.py para descobrir boletins semanais já publicados em HTML capturado legitimamente.

Fonte oficial verificada em 20/10/2026:
https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra

A página contém boletins de acompanhamento com paginação, incluindo o período 12 a 18/10/2026 e texto de última modificação 19/10/2026 19h20. A expressão 'última modificação' **não é prova de publicação original**, disponibilidade point-in-time, revisão de planilha ou percentuais agrícolas.

## Código entregue

- Identifica URL oficial, janela semanal segunda-domingo e transição entre anos.
- Conserva URL do boletim publicada, hash SHA-256 do HTML recebido, instante de captura em UTC e texto de modificação sem inferir fuso.
- Não gera URL a partir do calendário: usa somente o link presente no HTML.
- Consolida várias páginas recebidas externamente, detecta duplicatas e conflitos e aponta semanas omitidas na captura.
- A ausência de uma semana não prova inexistência de relatório.
- Não ativa HTTP, scheduler, download, inserção SQL, deploy ou publicação.
- Inclui testes unitários contra fixtures sintéticas.

## Uso somente em HTML local autorizado

```sh
PYTHONPATH=src python -m nivon.conab_progresso_indice \
  --html /caminho/privado/indice_conab.html \
  --url "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra" \
  --coletado-em "2026-10-20T20:00:00Z"
```

A CLI retorna manifesto JSON, não registros de plantio ou colheita. Para várias páginas locais, chamar consolidar_paginas com os dicionários html, url_indice e coletado_em.

## Gates de recuperação histórica real

1. Homologar por operação consulta, armazenamento, derivação e redistribuição.
2. Planejar aquisição controlada do índice em todas as páginas, sem contornar WAF ou termos de uso; implementar timeouts, limites, backoff e egress seguro.
3. Capturar RAW privado, cabeçalhos de resposta, URL final, SHA-256 e data de captura; exigir backup criptografado e restore testado.
4. Baixar cada boletim permitido, validar formato/MIME/layout e interpretar revisões com edição distinguível.
5. Integrar conteúdo ao conab_agrobr.py e progresso_conab_historico.py, com prova real dos bytes transformados, cultura/UF/safra e distinção de Brasil versus média de estados.
6. Validar E2E incremental, backfill, idempotência, revisão, falha de rede e corte temporal; somente depois avaliar execução agendada.

## Estado verificável

- Dataset catalogado: CODE_PRESENT.
- Boletins reais adquiridos ou persistidos por este incremento: **zero**.
- Primeiras publicações históricas verificadas: **zero**.
- Cobertura retroativa completa: **não atestada**.
- Gate de direitos e operacional permanece OFF.
- Testes precisam ser registrados no SHA final da PR; criar testes não significa executá-los.
