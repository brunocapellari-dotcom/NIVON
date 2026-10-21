# Prova de integridade da aquisição marítima

O pipeline `coleta_web.adquirir_fonte` já calcula SHA-256 a partir dos bytes HTTP. Em `portos_automaticos.processar_documento_porto`, a rotina agora **recalcula** o hash antes do parser e confere ainda tamanho, identidade `fonte_id`, formato MIME quando conhecido, assinatura PDF, URL exata do contrato e carimbo de captura com fuso.

Testes sintéticos cobrem substituição de conteúdo após a aquisição, hash falso, tamanho divergente, identidade de origem errada e horário/MIME inválidos. A aprovação de direitos é validada pelo `FonteWeb` existente e não foi afrouxada.

Esses controles provam consistência entre bytes recebidos e o parser, **não** a legitimidade do site, a adequação comercial, a completude da série ou a efetiva movimentação. A descrição `PROGRAMADO_NAO_REALIZADO` e a homologação portuária pendente permanecem. Nenhuma coleta agendada ou deploy foi ativado.
