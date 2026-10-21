# NIVON — Contratos ambientais ANA e INMET (19/10/2026)

## Resultado implementado
Módulo `ana_contrato.py`: planejamento offline de janelas de 30 dias para telemetria e 366 dias para séries convencionais e HidroSat. Proíbe endpoint legado e não supõe parâmetros de autenticação. Fonte: https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html

Módulo `series_ambientais.py`: SQLite local de versões ambientais por SHA, estação, métrica, dia da competência, referência, publicação e coleta. Rejeita mistura de fontes/unidades, duplicações, anomalias físicas e versões conflitantes. Consultas temporais `as-of` não incluem dados publicados ou coletados depois do corte e excluem publicação desconhecida. Ponte Tmin/Tmax é compatível com o motor de graus-dia, sem preencher lacunas.

## Dependência oficial ANA
A ANA publicou que o prazo da antiga ServiceANA foi prorrogado até **30/06/2026** e que o acesso à nova HidroWebService deve ser solicitado a **hidro@ana.gov.br**. Fonte oficial: https://www.ana.gov.br/telemetria1ws/EstacoesTelemetricas.aspx. Esse acesso pode exigir nome/instituição, CPF/CNPJ e contato — **não incluir credenciais nem esses dados pessoais no GitHub**.

**Não utilizar API legada por fallback**. Nova API requer credenciais, autorização por operação, tutorial e amostra real antes de implementar chamadas autenticadas. O plano das janelas é informativo e não faz HTTP.

## INMET
Falta identificar a URL/download específico e layout atualizado, confirmar licenças para armazenamento e redistribuição, capturar uma amostra real e implementar parser compatível. O módulo só armazena observações já normalizadas.

## Gates
- Tudo permanece offline, sem agendamento, sem deploy e sem publicação.
- Direitos declarados no contrato não substituem aprovação efetiva do fornecedor.
- SQLite local não substitui backup/restauração e armazenamento durável em nuvem.
- Passar em testes sintéticos não equivale a validação com dados observados ou previsão calibrada.
- Os datasets ANA_HIDRO e INMET_ESTACOES continuam CANDIDATE; sem falso estado CODE_PRESENT de coleta.

Testes: `tests/test_series_ambientais_ana.py`. Documentação oficial: [Swagger HidroWebService](https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html).
