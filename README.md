# NIVON — inteligência do agronegócio e logística

Plataforma de inteligência sobre agricultura, pecuária, preços, transporte de granéis, portos, clima e cadeias de suprimento. A utilização e a redistribuição de cada fonte dependem de seus respectivos direitos, inclusive quando houver aplicação comercial.

## Situação do projeto (26/10/2026)
**Em reorganização. Go-live e acesso privado NÃO comprovados por esta documentação.** A verdade operacional é o código mesclado na `main`, evidências dos testes e o estado conferido diretamente no Google Cloud; PR aberta, plano e teste sintético não significam produção.

A direção técnica e revisão das cinco frentes cabe a Claude. Bruno decide merges, autorização de `producao`, gastos, IAM e configurações do GitHub. Os executores só alteram os arquivos das suas frentes.

## Decisões vigentes
- **Um único provedor de execução:** Google Cloud. Não usar Vercel. Neon está em processo de substituição, sem desligamento antes de reconciliação aprovada.
- **Topologia desejada, ainda sujeita a homologação:** um terminal privado Cloud Run com IAP e um coletor Cloud Run Job; no máximo seis workflows e oito variáveis; catálogo único `config/fontes.yaml`.
- Código modular planejado: `nucleo/`, `fontes/<fonte>/`, `carga/`, `analise/`, `terminal/`, `ops/`, `experimental/`. Isto descreve a meta, **não** afirma migração concluída.
- Dados verdadeiros separados de sintéticos, preservando fonte, quatro datas, unidade, revisão, situação e direitos de uso. Dado ausente não equivale a zero.
- Meta financeira **R$ 0**, nunca garantia de ausência de custos: nenhum recurso pago nem alteração de IAM sem autorização.
- Este repositório **público** deve conter apenas código, documentação publicável e dados sintéticos; não publicar credenciais, dados privados ou séries protegidas.
- CEPEA somente para uso interno autorizado; licença de consulta não implica redistribuição.

## Documentos de referência
- [Arquitetura — provisória](docs/ARQUITETURA.md)
- [Operação — provisória](docs/OPERACAO.md)
- [Decisões](docs/DECISOES.md)
- [Fontes — responsabilidade F4, pendente](docs/FONTES.md)
- [Segurança — responsabilidade F5, pendente](docs/SEGURANCA.md)
- [Arquivo de documentos anteriores](docs/historico/)

## Fluxo de contribuição
Abrir issue → escolher `frente:F1` a `frente:F5` → implementar somente no escopo → apresentar relatório verificável na PR → revisão de Claude → merge manual de Bruno. Fechar PRs antigas e apagar branches somente com **APROVADO** explícito.

**Importante:** o repositório público não concede automaticamente licença aberta sobre o código. Respeitar licenças dos componentes e termos das fontes.
