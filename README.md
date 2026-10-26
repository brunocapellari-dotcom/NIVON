# NIVON — Inteligência de Mercado, Indústria e Logística

Plataforma independente de análise agroindustrial, de granéis e de logística do Brasil, com foco inicial em Mato Grosso.

## Estado

**Implementação inicial em andamento; NÃO HOMOLOGADO para uso operacional.**

Auditorias de 16/10/2026: **GO COM CONDIÇÕES para implementação**, não para go-live. Nenhuma saída sintética pode ser apresentada como observação real.

## Arquitetura de produção — Google Cloud único

O GitHub é exclusivamente repositório, revisão e CI. Hospedagem de interfaces, APIs, coletores e processamento do NIVON utiliza Google Cloud, com GCS, BigQuery, Cloud Run e Cloud Scheduler sob gates de IAM/billing. Configurações do Vercel e interface redundante foram aposentadas na PR de consolidação; a desconexão externa requer corte controlado. Ver [plataforma única](docs/PLATAFORMA_UNICA_GOOGLE_CLOUD.md). Não abrir novos projetos ou hospedagens em outros provedores.

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
