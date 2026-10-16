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

## Núcleo v0.1 (branch de desenvolvimento)

Primeira implementação **executável offline**. Componentes:

- `src/nivon/motores.py`: crescimento geométrico de consumo (3–5 anos) e cenário com última taxa; referência CEPEA exclusiva para margens com alerta de balanço físico; cálculo inverso somente quando a matéria-prima e tipo de etanol são conhecidos; classificação amostral de fluxos ANTT por NCM e zona ambígua; fonte bloqueada por padrão.
- `src/nivon/portos.py`: contrato programado de dez portos e contagem prudente de escalas. IMO sozinho não é identificador de escala.
- `config/portos_brasil.v1.json`: **catálogo**, sem conectores ativados nem fontes homologadas.
- `src/nivon/ingestao.py`: leitura local de CSV separado por ponto e vírgula com permissão por operação, limites, rejeição de nulos e schema, quatro datas e SHA-256; sem rede.\n- `tests/test_motores.py` e `tests/test_ingestao.py`: **25 testes offline com dados sintéticos**.

### Executar sem instalação ou credenciais

Python **3.11+**, em Linux/macOS:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m nivon
```

O script de demonstração usa apenas **valores sintéticos**, sem acessar a internet.

### Próximos gates

1. Conferir direitos por operação antes de qualquer conector real.
2. Preparar contratos canônicos e importadores offline para CONAB/Sindirações/ANTT/MAPA com schemas baseados em arquivos reais, **sem publicar os arquivos**.
3. Adaptar e validar individualmente parsers marítimos de fontes oficiais, com aquisição repetida e cobertura.
4. Reconciliar balanços (safra vs. ano civil, transporte vs. consumo, soja esmagada vs. farelo).
5. Testar persistência, segredos, segurança e operação sem dependência de outros projetos.

**Não há deploy, API exposta, banco em nuvem ou coleta operacional nesta versão.**
