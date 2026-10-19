# NIVON — Inteligência específica de cana, gergelim, frango e suíno

**Data:** 19/10/2026 · **Situação:** código e catálogo offline, não homologado com séries reais, sem coletores agendados ou deploy.

## Equivalência de implementação

As quatro cadeias têm: frente própria no catálogo canônico, datasets e rotas 1:1, indicadores e limitações, validação de observações por produto/unidade/calendário, hashes/vintages e direitos por operação, motores determinísticos reutilizando balanços, cenário CAGR e backtest, testes sintéticos, integração transversal com comércio exterior, ração, clima e logística. A maturidade operacional NÃO é equivalente: soja/milho possuem amostras históricas CONAB, estas quatro ainda exigem parsers e dados reais homologados.

## Matriz de motores e entregas

| Cadeia | Motor / arquivo | Entradas necessárias | Saídas e inteligência | Não permite inferir |
|---|---|---|---|---|
| CANA | `cadeias_adicionais.py`, `motores_cadeias.py`, `balancos.py` | área, produtividade, produção, moagem, ATR kg/t, mix ATR açúcar/etanol, recorte espacial, safra e fontes | produtividade, alocação de ATR, relação indicativa moagem/produção, balanço conservativo de cana; ligação com preço de açúcar, exportação e energia | toneladas de açúcar + litros de etanol somados; total ANP como etanol apenas de cana |
| GERGELIM | `conab_catalogo.py`, `cadeias_adicionais.py`, `motores_cadeias.py` | CONAB/IBGE área, produção; MDIC NCM com vigência; FOB; PTAX; frete/porto/custos declarados | produtividade calculada e reconciliada, valor FOB médio USD/t, cenário de paridade FOB→origem, sazonalidade e risco de mercado comprador | FOB como preço recebido, consumo estimado como estoque, atribuir município a exportação por UF |
| FRANGO | `cadeias_adicionais.py`, `motores_cadeias.py`, `balancos.py` | IBGE SIDRA 1094, carcaça kg, cabeças, ABPA, milho/farelo, formulação, conversão, MDIC NCM; alertas MAPA/WOAH | peso médio de carcaça, simulação de custos de ração/margem contributiva sob hipóteses, indicadores de exportação na mesma base física, sinais de doença e restrições | população total de aves a partir de abate inspecionado; peso de cortes = carcaça; preços livres sem licença |
| SUINO | módulos acima, SIDRA 1093 | abate, peso de carcaça, rebanho, ABPA, milho/farelo, conversão, MDIC, alertas sanitários | peso médio, custo alimentar, margem hipotética, intensidade de exportação na mesma unidade, pressão de insumos, riscos sanitários | rebanho = animais disponíveis para abate; peso vivo = carcaça; alertas sanitários = embargo comprovado |

## Matemática e unidades

- **Cana:** ATR total (kg) = cana moída (t) × ATR (kg/t). Os percentuais de alocação para açúcar e etanol devem totalizar 100%, mas o resultado permanece **ATR alocado em kg**, não açúcar em toneladas ou etanol em litros. O mix ATR real exige janela e geografia consistentes.
- **Gergelim:** produtividade (kg/ha) = produção (t) × 1000 / área (ha); FOB médio (USD/t) = FOB (USD) / quantidade exportada (t), se ambas as séries tiverem o mesmo recorte e produto; paridade hipotética (R$/t) = FOB (USD/t) × USD/BRL − custos explicitamente informados (R$/t). Não classificar como cotação física.
- **Frango e suíno:** carcaça média (kg/cabeça) = peso das carcaças (kg) / cabeças abatidas. Custo da ração (R$/t) = Σ fração de ingrediente × preço informado (R$/t). Custo por kg de ganho vivo = (custo da ração/1000) × conversão alimentar (kg de ração/kg de ganho), sob mesma base e hipóteses documentadas.
- **Carnes:** exportação e produção só são comparáveis se convertidas por metodologia válida para **equivalente-carcaça**; o `Balanco` exige esse atributo. A razão exportação/produção não é participação definitiva se houver estoques, importações ou divergência de coberturas.
- **Previsões:** `cenario_anual` usa `projetar_consumo` e `backtest_anual` compara CAGR com último valor sem look-ahead, ambos já existentes no NIVON. `modelo_validado` fica falso até validação fora da amostra com séries oficiais versionadas.

## Motores adicionais a homologar com dados históricos reais

1. **Oferta/uso/estoques:** IBGE/CONAB/ABPA/UNICA e MDIC, sem somar volume de matéria-prima ao derivado; separar safra de ano civil.
2. **Projeção de abate:** validar atividade, sazonalidade, alojamento e tempo de produção; não aplicar coeficiente biológico genérico sem fonte/corte.
3. **Custo industrial e frete:** consumo de ração a partir de plantel/abate só como hipótese documentada, não observação; integrar preço de milho, farelo e energia.
4. **Risco sanitário e comercial:** eventos MAPA e OMSA/WOAH com data, espécie, geografia, status suspeito/confirmado, medida oficial, compradores afetados; sem score/embargo inferido.
5. **Cana:** TCH, ATR, mix, janela de moagem, chuva, qualidade, preço relativo açúcar/etanol, paridade ICE e combustível; requer coeficientes de conversão e contratos de mercado válidos.
6. **Gergelim:** produtividade e risco hídrico de segunda safra, fluxo de exportação por NCM vigente, destinos, FOB, câmbio, portos, custos e concentração de compradores; modelar incerteza em séries curtas.

## Fontes/gates

- CONAB: GergelimSerieHist.xls está no índice oficial, mas a descoberta do link **não** equivale a leitura/normalização do XLS com layout real.
- IBGE: SIDRA 1093 (suínos), 1094 (frangos), trimestre/mês/BR/UF; validar variáveis/unidades reais, revisão e datas.
- ABPA: balanços anuais de produção, consumo e exportação, com direitos separados de coleta e republicação.
- MAPA: SAPCANA/relatórios canavieiros; sanidade oficial para frango e suíno; diferenciar suspeita, confirmação e embargo.
- MDIC: o parser de exportação já existente aceita NCMs explícitos, mas o dicionário por código/NCM/ano de vigência e produto fica pendente, sem NCM inventado.
- WOAH: sinais internacionais de enfermidades sujeitos a direitos/endpoint e validade temporal.

**Critério de aceite por cadeia:** histórico desde o início legal e acessível da fonte, parser de amostra real, normalização e hashes, quatro datas, publicação revisável/as-of, testes de balanço e unidade, pelo menos três execuções reais em dias de atualização pertinentes, qualidade reconciliada, persistência/backups e fonte com direito confirmado. Não habilitar deploy/coleta/redistribuição antes desses gates.
