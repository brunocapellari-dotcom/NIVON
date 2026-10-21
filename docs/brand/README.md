# NIVON — Identidade visual agro (v0.3)

**Estado:** direção criativa aprovada pelo usuário; esta versão técnica vetorial é **preliminar**, ainda sujeita a revisão antes do uso público. Sem registro de marca verificado.

O conceito reúne agronegócio, inteligência de mercado, dados e logística. O **N** foi reinterpretado com curvas de lavoura que representam movimento, linhas de plantio e conectividade. O símbolo exerce a função da **primeira letra do nome**, e as formas vetoriais seguintes compõem **IVON**, evitando ler "NNIVON". Esta é uma reconstrução vetorial original inspirada no painel aprovado, e não uma vetorização 1:1 dos pixels do material gerado por IA.

## Arquivos

| Arquivo | Uso principal |
|---|---|
| [logo-horizontal.svg](logo-horizontal.svg) | Marca em fundos claros |
| [logo-reverse.svg](logo-reverse.svg) | Marca para fundos verde profundo ou outros fundos escuros |
| [logo-monochrome.svg](logo-monochrome.svg) | Aplicações monocromáticas sobre fundos claros |
| [symbol.svg](symbol.svg) | Símbolo isolado / avatar / marca d'água |
| [app-icon.svg](app-icon.svg) | Ícone do aplicativo |
| [favicon.svg](favicon.svg) | Favicon e uso em dimensões reduzidas |
| [identity-preview.svg](identity-preview.svg) | Painel visual de referência técnica |
| [brand-tokens.json](brand-tokens.json) | Tokens de design para produtos digitais |
| [brand.css](brand.css) | Variáveis CSS para interface |
| [validate_brand.py](validate_brand.py) | Auditoria estrutural de marca e contraste |
| [export_png.py](export_png.py) | Geração local dos PNGs derivados |

Os SVGs de marca e os ícones são **vetoriais autossuficientes**, com letras desenhadas em caminhos; dispensam a instalação de fontes para o logo. A prévia contém textos de apresentação, que podem usar a fonte **Inter** (ou substitutas) sem incorporar arquivos de fonte.

## Paleta cromática

| Papel | HEX | Diretriz |
|---|---|---|
| Verde profundo | `#0B3D2E` | Cor institucional, fundo escuro, texto sobre areia |
| Verde agro | `#497142` | Cor secundária, elementos e detalhes |
| Dourado safra | `#DAA574` | Ênfase visual em fundo escuro |
| Areia | `#EDE6DB` | Fundo claro e áreas de respiro |
| Terra | `#3E2F20` | Apoio tipográfico e elementos de identidade |
| Branco | `#FFFFFF` | Contraste sobre fundos escuros |

Acessibilidade segundo WCAG (contrastes calculados): verde profundo sobre branco **12,20:1**, verde profundo sobre areia **9,84:1**, verde agro sobre branco **5,64:1**, verde agro sobre areia **4,55:1**, dourado sobre verde profundo **5,59:1**. **Não usar** dourado sobre branco para textos: contraste **2,18:1**. Não transmitir o sentido de altas/baixas de indicadores apenas por cor.

## Regras

1. Não distorcer, rotacionar, adicionar efeitos 3D ou aplicar sombras ao logotipo.
2. Preservar área de respiro de pelo menos **1/4 da altura do símbolo** entre a marca e outros elementos.
3. Recomenda-se mínimo de **160 px de largura** para o logotipo horizontal em telas; usar ícone/símbolo em espaços menores.
4. Para tamanhos de 16 px, usar o favicon simplificado.
5. O tagline **"Inteligência para mover o agro."** é uma proposta editorial, não parte estrutural obrigatória do logotipo.
6. Não colocar símbolo de marca registrada e não divulgar telefone, endereço, URL, parcerias ou credenciais fictícias.
7. O **IVO** é produto/submarca distinto; sua identidade deve ser desenvolvida separadamente, mantendo parentesco visual com o NIVON.

## Testes e exportações

Executar a partir da raiz do repositório:

```bash
python docs/brand/validate_brand.py
python -m pip install cairosvg  # opcional para exportação PNG
python docs/brand/export_png.py --output-dir /tmp/nivon-png
```

O código de validação utiliza a biblioteca padrão do Python. A exportação para PNG depende de CairoSVG. A inspeção visual deve abranger transparência, fundo branco e verde profundo, 16/32/64/192 px, e verificações humanas antes do lançamento. Os PNGs são derivados, não a fonte canônica.

## Limites e procedência

A identidade visual foi gerada em conversa, e sua reconstrução vetorial foi elaborada para permitir manutenção em ferramentas gráficas. O arquivo PNG conceitual não foi incorporado ao repositório público nesta etapa; esta versão **não** é uma cópia pixel a pixel do painel. A publicação no GitHub não confere licença aberta para exploração da marca. **Aprovação visual definitiva, disponibilidade marcária e liberação para uso comercial continuam pendentes.**
