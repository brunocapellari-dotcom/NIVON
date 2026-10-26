# NIVON — Inteligência de Mercado, Indústria e Logística

Plataforma independente de análise agroindustrial, de granéis e de logística do Brasil, com foco inicial em Mato Grosso.

## Estado

**Implementação inicial em andamento; NÃO HOMOLOGADO para uso operacional.**

Auditorias de 16/10/2026: **GO COM CONDIÇÕES para implementação**, não para go-live. Nenhuma saída sintética pode ser apresentada como observação real.

## Diretrizes vinculantes

- Somente código, documentação e dados sintéticos publicáveis neste repositório público. **Nunca** credenciais, arquivos privados ou séries de terceiros sem direito de redistribuição.
- Custos de implantação e operação: objetivo **R$ 0**; nenhuma contratação ou deploy sem autorização.
- Fontes de dados: permissões separadas por operação; direitos restritos ou desconhecidos implicam **bloqueio por padrão**.
- Dados OBSERVADOS, INFORMADOS, ESTIMADOS, INFERIDOS e PROJETADOS jamais são intercambiáveis.
- Dados ausentes são ausentes, não zeros imputados.
- Não misturar ano civil e safra sem mapeamento explícito; preservar competência, referência, publicação e coleta.
- CEPEA: 440 L etanol, 331 kg DDG, 20,4 L óleo por t de milho são **parâmetros de análise de margem**, não um trio automaticamente válido para balanço físico.
- ANTT/MDF-e: recortes por NCM são amostrais, e municípios com terminal e fábrica são AMBÍGUOS; jamais publicar volume amostral como total observado.
- Line-up PROGRAMADO não é realizado; aquisição de página não é operação portuária concluída.
- Reuso de projetos antigos exige proveniência/licença/testes e não pode forçar dependências em BigQuery, Cloud Run, Hermes ou Holding.

## Desenvolvimento

O trabalho de implementação inicial ficará em uma branch e em PR para revisão. Os testes locais usam somente fixtures sintéticas. A aprovação dos auditores não equivale à homologação operacional.

## Licenciamento do código

**Ainda não foi concedida uma licença aberta para este código.** A visibilidade pública do repositório não deve ser interpretada como permissão genérica de cópia ou sublicenciamento. Componentes de terceiros só serão incorporados após exame das respectivas licenças.

## Integrações GitHub e fontes reutilizadas (26/10/2026)

- **Inventário canônico:** `config/catalogo_integracoes_github_20261026.json` — 33 projetos avaliados e 55 datasets agrobr listados, com licenças e estados. Consulta: `python -m nivon.catalogo_github`.
- **Coletores já incorporados:** `src/nivon/anp_ppi.py` (PPI ANP) e `src/nivon/agrobr_mercados.py` (Comex Stat/CFTC).
- **Novos adaptadores setoriais, ainda sem testes:** `src/nivon/agrobr_setoriais.py` (IBGE PPM, abate, leite, produção anual, PIB agro e ANP diesel revenda). Reutilizam o ledger existente; não criam serviços novos.
- **Registro de inclusão e pendências:** `docs/INCLUSAO_INTEGRAL_FONTES_GITHUB_NIVON_20261026.md`.

**Registro no GitHub não é coleta comprovada.** Os testes foram adiados a pedido do proprietário. Nenhum dado novo foi publicado no terminal ou carregado no Google Cloud por essa inclusão; componentes com licença ou permissão não confirmada continuam apenas referenciados.
