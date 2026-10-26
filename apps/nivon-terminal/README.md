# NIVON Terminal — prévia técnica read-only

Primeira interface executável do NIVON, em `apps/nivon-terminal`.

- Não acessa Neon, BigQuery, GCS, dados privados, AIS, fretes ou credenciais.
- Mostra apenas 2022–2025 ANTT/SIADE e a amostra rodoviária RGI 2025 já demonstradas em logs públicos do repositório.
- Monitora exclusivamente *metadados públicos* de execuções do GitHub Actions em tempo de visita.
- Sucesso de workflow = execução técnica, **nunca frescor da fonte nem autorização de publicação dos preços**.
- Não inclui cotações, preços, dados de pessoas, inferências marítimas ou números sintéticos.
- Sem backend, banco ou cron adicional. Layout responsivo, sem dependências de NPM.
- Controles: CSP, noindex, fetch público sem credenciais e links para evidência.

Para testar localmente: `python -m http.server 8000 --directory apps/nivon-terminal`.
Testes: `python -m unittest discover -s tests -p 'test_terminal_publico.py' -v`.
CI: `.github/workflows/nivon-terminal-ci.yml`.

**Escopo de go-live:** prévia pública de evidências, não a homologação completa do NIVON. Dados operacionais privados requerem backend autenticado, revisão de licenças, IAM, orçamento e testes de aceitação E2E antes de ativação.

Referências ferroviárias: execução ANTT [39998589364](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39998589364); multimodal [40010743069](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40010743069).
