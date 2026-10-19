"""Deduplicação editorial conservadora entre portais: mesmo evento, não só título idêntico.

Opera sobre notícias já verificadas (direitos, publicação com hora/fuso, janela 24h).
Não reclassifica atualização de página como notícia nova.
"""
from __future__ import annotations
import re
import unicodedata
from difflib import SequenceMatcher

STOPWORDS = frozenset({"a","o","as","os","de","da","do","das","dos","no","na",
                       "nos","nas","em","para","por","com","que","um","uma","ao",
                       "atinge","chega","segundo","mostra","registra","indica"})
ENTIDADES = frozenset({"soja","milho","verao","safrinha","algodao","boi","trigo",
                       "sorgo","acucar","ureia","fertilizantes","diesel","etanol",
                       "paranagua","santos","itaqui","frango","suino"})
ETAPAS = frozenset({"plantio","colheita","exportacao","importacao","embarque",
                    "desembarque","producao","greve","preco","estoque","estiagem"})


def tokens(titulo: str) -> set[str]:
    s = unicodedata.normalize("NFKD", titulo).encode("ascii","ignore").decode("ascii").lower()
    return {x for x in re.findall(r"[a-z0-9]+",s) if len(x)>1 and x not in STOPWORDS}


def mesmo_evento(primeiro: dict, segundo: dict) -> bool:
    a,b = tokens(primeiro["titulo"]),tokens(segundo["titulo"])
    if not a or not b:
        return False
    # Produto ou estágio diferente não deve ser consolidado.
    ea,eb=a&ENTIDADES,b&ENTIDADES
    if ea and eb and not ea&eb:
        return False
    sa,sb=a&ETAPAS,b&ETAPAS
    if sa and sb and not sa&sb:
        return False
    na = {x for x in a if x.isdigit()}
    nb = {x for x in b if x.isdigit()}
    if na != nb:
        return False
    intersection=len(a&b)
    union=len(a|b)
    similaridade=intersection/union
    sequencia=SequenceMatcher(None," ".join(sorted(a))," ".join(sorted(b))).ratio()
    return intersection>=3 and (similaridade>=0.52 or (intersection>=4 and sequencia>=0.78))


def deduplicar_eventos(noticias: list[dict]) -> tuple[list[dict],list[dict]]:
    """Consolida apenas equivalências fortes, mantendo a primeira publicação elegível.

    Notícias de categoria ou estágio diferente não são automaticamente fundidas.
    """
    escolhidos=[]
    rejeitados=[]
    for item in sorted(noticias,key=lambda n:n["publicado_em"]):
        anterior=next((n for n in escolhidos if mesmo_evento(n,item)),None)
        if anterior:
            rejeitados.append({"titulo":item["titulo"],"motivo":"mesmo acontecimento já representado",
                               "referencia_titulo":anterior["titulo"]})
        else:
            escolhidos.append(item)
    return escolhidos,rejeitados
