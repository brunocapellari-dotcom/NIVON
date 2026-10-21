# Boletim diário: arte, dados e texto curto

O modelo do **RESUMO ESTRATÉGICO DO AGRONEGÓCIO** está aqui como fonte editável e governada. Esta pasta faz parte do NIVON internamente, mas o **nome e o logo do NIVON não aparecem na arte pública**.

## Arquivos
- PADRAO_EDITORIAL.md — especificação aprovada e regra para o texto que acompanha a imagem.
- ../../templates/briefing/modelo_visual.html — apresentação vertical verde/dourado, sem imagens nos corredores.
- ../../templates/briefing/edicao_exemplo_2026-10-21.json — estrutura preenchível com um exemplo histórico.
- ../../scripts/briefing/render_briefing.py — gera PDF do HTML + JSON.

## Preenchimento diário
1. Copiar o JSON da edição anterior para um novo arquivo de data; substituir **todos os fechamentos e as notícias** com dados confirmados. Atualizar contrato, fonte, data e unidade. Não reaproveitar cotações como atuais.
2. Atualizar **os três corredores principais** (Sorriso–Rondonópolis, Sorriso–Dom Aquino e Sinop–Miritituba) e as três referências adicionais, distinguindo frete informado e volumes de referência de volumes realizados.
3. Preparar a frase de WhatsApp no campo whatsapp_intro, factual e sem caráter comercial.
4. Fazer a revisão editorial e de proveniência.
5. Renderizar PDF, conferir visualmente e exportar PNG para o WhatsApp.

## Renderização local

Requisitos: Python 3.11 ou superior, Jinja2, WeasyPrint.

    pip install Jinja2 WeasyPrint
    python scripts/briefing/render_briefing.py templates/briefing/edicao_exemplo_2026-10-21.json briefing.pdf

O exemplo não comprova ingestão atualizada, validade das notícias na janela de 24h ou funcionamento de publicador WhatsApp. Não efetuar publicação sem revisão dos dados.
