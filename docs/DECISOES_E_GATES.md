# Decisões vinculantes e gates de implementação — 16/10/2026

## Estado das auditorias

- Cinco bloqueadores metodológicos: **RESOLVIDOS COM CONDIÇÕES DE IMPLEMENTAÇÃO**.
- Sem bloqueador P0 documental; **GO COM CONDIÇÕES para desenvolver**.
- Homologação operacional **PENDENTE**. Não confundir código local com operação real.

## Motores iniciais

1. **Consumo de ração** — crescimento geométrico médio de 3 a 5 anos como cenário principal, 1–2 anos de horizonte; última taxa anual apenas como sensibilidade. Fonte Sindirações requer direitos por operação e reconciliação com CONAB (ano civil vs. safra, e não somar parcela de ração novamente).
2. **Indústria de milho** — coeficientes CEPEA de 2026: **440 L etanol, 331 kg DDG, 20,4 L óleo por t de milho**, EXCLUSIVAMENTE como parâmetros de margem. No cenário de milho a 14% de umidade e DDG a 11%, o trio excede o teto de massa seca, portanto NÃO entra diretamente no balanço físico. Tipo de etanol e matéria-prima são obrigatórios para cálculo inverso; produção total de etanol por UF que misture cana e milho é `NAO_IDENTIFICAVEL`.
3. **ANTT/MDF-e** — registros de produto filtrados por NCM não representam todo o volume da ANTT; a ANTT aponta identificação de NCM em parcela limitada dos registros. Rotular como `OBSERVADO_AMOSTRAL_NCM`, calcular cobertura apenas com totais apropriados do painel, não extrapolar por regra de três. Considerar carga própria e terceiros. Municípios com terminal E fábrica são `AMBIGUO`, não excluir dados originais. Cadastro SIPEAGRO do MAPA é localizador, não prova de consumo.
4. **Portos** — dez portos brasileiros no manifesto, todos sem homologação neste núcleo. Programação não comprova embarque, atracação, desatracação ou tonelagem realizada. Coleta de PDF/HTML real depende de gate de direitos, aquisição repetida, formato e teste de regressão. Sem AIS contínuo na v0.1; computador desligado não observa trajetórias.
5. **Segurança** — consulta, coleta, armazenamento, uso comercial e redistribuição devem ser autorizados por operação. Tudo PENDENTE = bloqueado. Nenhum arquivo de fonte real, segredos, dados privados, token ou chave no GitHub público.
6. **Reuso** — os componentes antigos têm licenças não demonstradas como permissivas; portanto esta versão usa implementação independente. Não copiar código do AgroLog ou de outros projetos sem prova de direitos. BigQuery, Cloud Run, Hermes e Holding NÃO são dependências.
7. **Infraestrutura** — v0.1 local sob demanda, sem integração com API real, sem deploy, custo adicional zero. Persistência, backup, API e portos operacionais exigirão gates próprios.

## Evidência dos testes

`PYTHONPATH=src python -m unittest discover -s tests -v`

A suíte inicial usa **apenas dados sintéticos**. Antes de promoção de um conector, exigir prova de licença, cobertura, aquisição real repetida, fidelidade das linhas e tratamento de falhas, sem colocar os dados coletados no repositório.

## Origem dos requisitos

Parecer resumido de auditoria independente de 16/10/2026 e "NIVON — Parecer de Auditoria Externa Final (Claude)", 16/10/2026. Este documento resume decisões de engenharia; não transcreve nem redistribui o PDF da auditoria.
