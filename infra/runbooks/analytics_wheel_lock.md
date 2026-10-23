# Analytics Wheel Lock — etapa de captura e posterior imposição

O pipeline `infra_analytics_experiment.yml` baixa somente wheels da PyPI pública e verifica cada arquivo com SHA-256. Para tornar as dependências transitivas realmente reproduzíveis, `src/nivon/infra_wheel_lock.py` cria um inventário determinístico de **nome exato, tamanho e SHA-256** por arquitetura, incluindo imagem-base por digest e constraints do `pyproject.toml`. Ele imprime apenas metadados públicos de arquivos PyPI e nenhuma credencial/URL assinada. O lock é separado para AMD64 e ARM64 porque os wheels nativos são diferentes.

Na primeira execução, captura os manifests nas evidências do CI; depois que ambos forem versionados em `infra/locks/analytics-{amd64,arm64}.json`, o mesmo workflow exige igualdade estrita antes de executar qualquer build com as wheels. Uma modificação inesperada de dependência transitiva **falha o CI**. A captura inicial não significa que o lock foi aprovado ou que assinaturas/licenças/CVEs dos pacotes tenham sido revisadas.

O lock é apenas da imagem analítica experimental; não promove release, não libera os 44 HIGH do Debian, não implanta serviços e não consulta fontes de dados.
