# Padrão editorial aprovado — Resumo Estratégico do Agronegócio

Status: **modelo editorial de publicação aprovado**. Não significa coletores ou WhatsApp homologados.

## Formato público
- Título **RESUMO ESTRATÉGICO DO AGRONEGÓCIO**.
- Arte vertical, profissional e legível no celular. Paleta verde profundo, verde agro, dourado safra e areia/branco.
- **Sem nome NIVON, logotipo, símbolo ou assinatura de marca** no PDF/PNG público. Manter apenas a linguagem visual.
- Corredores principais em **cartões somente textuais**, sem fotos de caminhões, barcaças, estrada, rios ou ilustrações decorativas.
- Entregar PDF, PNG compartilhável e um texto curto **separado da imagem**.

## Ordem fixa
1. Título, data, notícias publicadas nas últimas 24h.
2. Cotações do último fechamento: CME/Chicago (soja, milho, trigo), físico (soja Paranaguá e Sorriso, milho Cepea/Campinas e Sorriso), pecuária (boi Cepea/SP, Sinop/MT e B3), ICE/NY (café, algodão, açúcar), B3 futuros se disponível, energia/câmbio (etanol, Brent, dólar e PTAX se validada).
3. Fretes: Sorriso–Rondonópolis, Sorriso–Dom Aquino, Sinop–Miritituba, com R$/t e volume de referência em t/dia. Rotas complementares Sorriso–Paranaguá, Sorriso–Santos e Sorriso–Uberaba.
4. Notícias breves por tema e sem repetição.
5. Fontes/datas e ressalvas discretas no rodapé.

**Não incluir:** impactos, resumo executivo final, seção monitorar, publicidade, convite de compartilhamento ou CTA.

## Texto de acompanhamento (externo à arte)
Exemplo aprovado:

> Bom dia!
>
> Quarta-feira começa com queda dos grãos em Chicago, avanço do plantio da soja no Brasil e novas projeções para as exportações.

Escrever a cada dia uma frase de síntese com até três fatos relevantes e confirmados. Sem slogan, autopromoção, percentuais em excesso ou repetição de tabela. A mensagem não pode parecer venda de produto.

## Governança dos dados
- Trocar apenas dados e notícias a cada edição; **não** reutilizar preço histórico como se fosse atual.
- Registrar no dado de produção: data_referencia, data_publicacao, data_coleta, competencia, fonte, link, contrato, unidade e tipo de evidência, conforme aplicável.
- Notícias precisam de publicação verificável **dentro da janela móvel de 24 horas** contada da geração.
- Fretes fornecidos pelo usuário = referências informadas, **não** cotações negociadas nem valores pagos/contratados.
- Volumes de referência = dados informados de operação ou capacidade não classificados como movimento realizado; não confundir com toneladas efetivamente recebidas.
- Exemplos históricos **não** substituem consulta da fonte oficial atualizada; dados ausentes são ausentes.
- O JSON é fonte de dados da edição; PDF/PNG são produtos derivados e jamais devem ser editados manualmente para trocar preço.

## Arquivos e status
- templates/briefing/edicao_exemplo_2026-10-21.json: edição de demonstração, não coleta ativa.
- templates/briefing/modelo_visual.html: template editável para preenchimento.
- scripts/briefing/render_briefing.py: renderizador de PDF a partir de JSON e HTML.
- A referência visual aprovada foi gerada em PDF a partir da última arte, oferecida ao usuário nesta conversa.
- O modelo editorial aprovado **não equivale** a automação ou integração operacional ativa.
