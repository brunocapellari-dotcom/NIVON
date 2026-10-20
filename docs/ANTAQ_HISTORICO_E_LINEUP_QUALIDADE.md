# NIVON — Dados de movimentação ANTAQ e validação do line-up

**Data da pesquisa:** 19/10/2026. **Escopo:** código offline, sem ativar rede, sem custos, sem deploy.

## 1. Fonte oficial e recuperação histórica

O Plano de Dados Abertos 2026–2028 da ANTAQ declara o Estatístico Aquaviário como base de
dados públicos de movimentação, com periodicidade mensal e histórico desde 2010.
PDA: https://www.gov.br/antaq/pt-br/acesso-a-informacao/dados-abertos/PDA20262028ANTAQOCR.pdf
Portal citado no próprio PDA: https://web3.antaq.gov.br/ea/sense/download.html

Formato documentado pelo AgroBR 2.0:
- arquivo anual `https://estatistica.antaq.gov.br/ea/txt/{ANO}.zip`, contendo
  `{ANO}Atracacao.txt` e `{ANO}Carga.txt`;
- `https://estatistica.antaq.gov.br/ea/txt/Mercadoria.zip`, contendo `Mercadoria.txt`;
- TXT CSV com delimitador `;`, codificação a validar e valores decimais PT-BR;
- chaves `IDAtracacao` (carga para atracação), `CDMercadoria` (catálogo de produtos).

**Atenção:** estes são URLs documentados/candidatos, NÃO endpoints com download testado
nesta execução. O AgroBR registra bloqueios/indisponibilidade por WAF e a reativação
do SDP em 08/10/2026 apenas restabeleceu o envio de informações por operadores,
não comprova a disponibilidade atual dos ZIPs públicos.
Fonte: https://www.gov.br/antaq/pt-br/noticias/2026/sistema-de-desempenho-portuario-esta-de-volta-em-nova-plataforma

`src/nivon/antaq_historico_offline.py` processa **arquivos já obtidos legalmente**,
sem HTTP. Faz validação de ZIPs, streaming de linhas em SQLite, conferência de chaves,
tipos e datas, hash por edição, rollback em fonte inconsistente e idempotência.
Séries históricas são movimentação observada; nunca devem virar line-up de hoje.

## 2. Novos acessos oficiais encontrados

- CDP: https://www.cdp.com.br/companhia-docas-do-para/programacao-de-navios/
  - índice contempla Vila do Conde/SCAP, Belém, Miramar, Outeiro e Santarém;
  - página Santarém: https://www.cdp.com.br/programacao-de-navios-do-porto-de-santarem/
  - a tabela possui linhas antigas (ex. 2022). Agendar coleta sem filtrar
    data da linha produz falseamento de situação atual.
- Portos RS: https://www.portosrs.com.br/site/
  - links para esperado, programado, em operação, fundeado e line-up de Rio Grande;
  - link de line-up direciona a `portoweb/.../login/logar/`, e a verificação pública
    encontrou loop de redirecionamento; **não contornar**.
  - PDFs antigos podem estar indexados; data do PDF não substitui estado atual.

## 3. Bloqueio editorial de line-up antigo

`src/nivon/qualidade_lineup.py` exige direitos comprovados,
DUV por escala, timestamps de publicação, coleta e referência (com fuso),
e rejeita linhas sem atualidade ou com unidade de tonelagem não verificada.

Apenas dados elegíveis formam indicadores `PORTOS` consumíveis pelo
`briefing_composto.montar_briefing`. Os testes simulam páginas antigas
de 2022 e 2025 consultadas em 2026, e recusam a interpretação equivocada.

Se nenhum registro é elegível, **não** informar que o porto possui zero navios;
exibir `DADO_INDISPONIVEL` com motivo na observabilidade de coleta.

## 4. Testes e gates

```sh
PYTHONPATH=src python -m unittest tests.test_antaq_historico_offline tests.test_qualidade_lineup -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

Pendente para go-live:
1. Confirmar em fonte oficial os ZIPs realmente acessíveis e direitos de redistribuição.
2. Testar três capturas reais por porto; controlar licenças e timestamps por fonte.
3. Agendar e persistir de modo durável em nuvem, com backup/restore e orçamento autorizado.
4. Homologar volumes e cargas ANTAQ contra estatística oficial agregada.
5. Conectar a montagem de quadro portuário ao motor E2E, somente após aprovar fontes reais.
6. Verificar se uma eventual revisão do esquema ANTAQ mudou `IDCarga`, `Ano`,
   `Mes`, `VLPesoCargaBruta` ou demais campos usados no parser. Mudanças exigem
   homologação: falhar fechado é preferível a fabricar dados.
7. Conservar a distinção entre fonte oficial, amostra de teste e evidência de operação.
