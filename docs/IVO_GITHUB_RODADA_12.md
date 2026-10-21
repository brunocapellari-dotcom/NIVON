# IVO — Rodada 12: consistência semântica PAM e índice de erratas identificadas

**Data de referência:** 21/10/2026. **Escopo:** correção de contrato, pesquisa pública e
validação offline. Não houve coleta real via SIDRA nesta rodada, criação de
licenças, treino de dados reais, deploy, merge, instalação de pacotes ou custo.

## Erro detectado antes do uso com dados reais

Na Tabela 1612 do SIDRA, as correspondências são diferentes das inicialmente
empregadas nas **fixtures sintéticas** de testes:
- variável **109** → área plantada, em **Hectares**;
- variável **214** → quantidade produzida, em **Toneladas**;
- categoria C81 **2692** → arroz (em casca);
- categoria C81 **2713** → soja (em grão);
- categoria C81 **2711** → milho (em grão);
- categoria C81 **2714** → sorgo (em grão).

Fontes de contextualização e investigação cruzada:
- [IBGE/PAM Tabela 1612](https://sidra.ibge.gov.br/tabela/1612)
- [Portal IBGE – PAM e suas tabelas](https://sidra.ibge.gov.br/pesquisa/pam/tabelas/)
- [Exemplo de especificação de código C81 para soja publicado pela Embrapa](https://www.alice.cnptia.embrapa.br/alice/bitstream/doc/1103773/1/2019cpamtagrossilvipastorilpart1cap2manejosolosojamatogrossop3338.pdf)
- [Códigos municipais oficiais do IBGE](https://www.ibge.gov.br/explica/codigos-dos-municipios.php)

As fixtures antigas associavam **109/2692/Toneladas**, uma combinação
semanticamente incompatível. Não há evidência de que tenham alimentado
modelos reais: eram dados fictícios. Esta rodada **corrige os testes**
para **214/2713/Toneladas** e impõe o contrato ao ingresso de dados PAM no IVO,
deixando os conectores genéricos do NIVON intactos.

## Código

1. `src/nivon/ivo_pam_semantica.py`: whitelist explícita das quatro
   categorias C81 verificadas e duas variáveis; código, grandeza, unidade,
   família (MASSA ou AREA), produto canônico e bloqueio por conflito.
   Não extrapola IDs ainda não auditados para outros produtos, rendimento,
   preços, área colhida ou unidades especiais. A expansão deve ser feita
   mediante validação oficial dos metadados e testes.

2. `src/nivon/ivo_pam_bridge.py`: chama o gate ANTES de normalizar
   o payload; falhas viram `ErroPontePAM`, mantendo o contrato externo
   existente. Tanto retornos numéricos quanto marcadores de indisponibilidade
   preservam o metadado semântico. Nenhum valor é automaticamente
   `OBSERVADO` certificado ou autorizado para treinamento.

3. `config/ivo_erratas_pam_identificadas.v1.json`: índice parcial com
   anúncios reais identificados no [Erramos do IBGE](https://www.ibge.gov.br/erramos.html):
   - **Tangará da Serra-MT / 5107958 / soja / PAM 2021**, aviso 17/09/2026;
   - **Arandu-SP / 3503109 / sorgo / PAM 2020, 2022 e 2023**,
     aviso 17/09/2026.
   O aviso identifica o escopo e a existência da correção, **não contém
   aqui os bytes da primeira versão, bytes da versão corrigida, comprovante
   de licença, assinatura documental ou quantidade anterior**.
   Campos preservam essas ausências e não permitem classificá-las
   como coletadas.

4. `src/nivon/ivo_radar_erratas_pam.py`: cruza município/ano/categoria
   C81/variável **214 (quantidade produzida)** com os avisos conhecidos,
   mantendo o corte da notícia, declarando a cobertura parcial do índice e
   que nenhum valor histórico foi reconstruído. Recusa fonte não oficial,
   novos códigos não revisados, URLs adulteradas, status de documentação
   indevidamente promovidos e IDs de errata duplicados.

5. Testes: `test_ivo_pam_semantica.py` e
   `test_ivo_radar_erratas_pam.py`, ampliação de
   `test_ivo_pam_bridge.py`, e migração das fixtures de
   `test_ivo_pam_publicacoes.py` e
   `test_ivo_pam_benchmark_anual.py`.
   Cobrem área/hectare versus produção/tonelada, soja versus arroz,
   soja versus sorgo, semântica desconhecida, datas futuras,
   índice limitado, eventos e municípios afetados.

## Estado verdadeiro e próximo trabalho

**Entregue:** auditoria semântica e radar **de anúncios oficiais**, integrados
em código e testados com fixtures. Não se afirmou performance real de
previsões ou disponibilidade de qualquer valor corrigido da PAM.

**Ainda falta:** localizar/arquivar bytes de versões **anteriores** das séries
PAM, comprovar publicação/captura de cada uma, metadados oficiais da variável
e da categoria com vigência, controlar licenças por operação e obter
autenticação/revisão independente. Não se pode recuperar um valor antigo a
partir da data de uma errata. Depois disso: benchmark anual real no ambiente
de homologação, separado de safra CONAB e laboratório mensal.

**Política:** sem dados verdadeiramente certificados, não permitir treino,
promoção de modelo ou divulgação de métricas como desempenho efetivo.
