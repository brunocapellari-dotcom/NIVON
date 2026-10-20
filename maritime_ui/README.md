# NIVON Maritime Cockpit (STAGING, nao homologado)

Interface MapLibre + deck.gl de origem AgroLogMT. Copiada para preservar o mapa, o replay, a tabela de line-up e os paineis de saude de fontes. O código visual **nao e um deploy, nao atesta AIS real nem cobre os portos nacionais**.

Para compilar quando houver Node/npm disponiveis: npm ci && npm run build
Para iniciar localmente: npm run dev

A variavel de endereco API de desenvolvimento e VITE_NIVON_GATEWAY_URL, caso exista um Gateway privado apropriado. **A API /v1/maritime/* nao foi migrada, e nao ha endpoint pronto nesse pacote.** Sem API, apresentar estado sem dados; nunca simular navios live como reais.

Dependencias vieram do package-lock legado, para auditoria de vulnerabilidades/licencas e build independente antes de deploy. O mapa-base de desenvolvimento usa serviço externo de demonstracao; operar custo zero e direitos de tiles exige politica/infra homologada.

Os textos de exemplos e zero-cost.html sao referencia visual, nao dados em tempo real. Autorizacao de consulta, entrega a terceiros, protecao de API e custeio precisam ser decididos antes de liberar o cockpit.
