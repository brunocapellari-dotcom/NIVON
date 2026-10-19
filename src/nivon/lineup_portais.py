"""Leitores OFFLINE para line-ups públicos de Itaqui e CODEBA.

Isolamento importante: HTML pode ter linhas antigas, datas sem hora ou quantidade
sem unidade explicitada. O parser NÃO transforma "Qtd. Carga" em toneladas, não
atribui timestamp de publicação fictício e não publica navios automaticamente.
Obtenção HTTP passa pelo coletor web autorizado da plataforma.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .lineup_nacional import instante

FONTES = {
    "ITAQUI": ("www.portodoitaqui.com.br", "/porto-agora/navios"),
    "ARATU": ("www.codeba.gov.br", "/eficiente/sites/portalcodeba/pt-br/porto_aratu.php"),
    "SALVADOR": ("www.codeba.gov.br", "/eficiente/sites/portalcodeba/pt-br/site.php"),
    "ILHEUS": ("www.codeba.gov.br", "/eficiente/sites/portalcodeba/pt-br/site.php"),
}
SECOES = (
    ("NAVIOS ATRACADOS", "ATRACADO"),
    ("NAVIOS FUNDEADOS", "AO_LARGO"),
    ("NAVIOS ESPERADOS", "ESPERADO"),
    ("NAVIOS DESPACHADOS", "DESPACHADO"),
    ("PROGRAMACAO DE NAVIOS - ATRACADOS", "ATRACADO"),
    ("PROGRAMACAO DE NAVIOS - ESPERADOS", "ESPERADO"),
    ("PROGRAMACAO DE NAVIOS - DESPACHADOS", "DESPACHADO"),
    ("PROGRAMACAO DE NAVIOS - FUNDEADOS", "AO_LARGO"),
    ("PROGRAMACAO DE NAVIOS", "PROGRAMADO"),
)
MAPA = {
    "NAVIO":"navio", "IMO":"imo", "DUV":"duv",
    "CARGA":"carga", "CARGA / TIPO DE SERVICO":"carga",
    "QTD.CARGA":"quantidade", "QTD CARGA PREV":"quantidade",
    "ULTIMA ATUALIZACAO":"ultima_atualizacao",
    "PREV CHEGADA":"eta", "ETA":"eta", "BERCO":"berco",
}


class ErroPortal(ValueError):
    pass


def _norm(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", text)
    return " ".join(re.sub(r"[^A-Z0-9./ -]", " ", "".join(c for c in s if not unicodedata.combining(c)).upper()).split())


class _TabelasPorSecao(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.secao = None
        self.em_heading = 0
        self.texto_heading = []
        self.tabela = None
        self.linha = None
        self.celula = None
        self.tabelas = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag) and self.tabela is None:
            self.em_heading += 1
            self.texto_heading = []
        elif tag == "table":
            if self.tabela is not None:
                raise ErroPortal("tabelas aninhadas")
            self.tabela = []
        elif tag == "tr" and self.tabela is not None:
            self.linha = []
        elif tag in ("th", "td") and self.linha is not None:
            if self.celula is not None:
                raise ErroPortal("célula aninhada")
            if any(k in {"rowspan", "colspan"} for k, _ in attrs):
                raise ErroPortal("rowspan/colspan requer layout específico")
            self.celula = []

    def handle_data(self, data):
        if self.celula is not None:
            self.celula.append(data)
        elif self.em_heading:
            self.texto_heading.append(data)
        elif self.tabela is None:
            # Páginas legadas CODEBA às vezes usam <strong> / <p> em vez de <h3>.
            heading = _norm(data)
            if 8 < len(heading) < 110:
                for nome, status in SECOES:
                    if heading.startswith(_norm(nome)):
                        self.secao = status
                        break

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.celula is not None:
            self.linha.append(" ".join(" ".join(self.celula).split()))
            self.celula = None
        elif tag == "tr" and self.linha is not None:
            if self.linha:
                self.tabela.append(self.linha)
            self.linha = None
        elif tag == "table" and self.tabela is not None:
            if self.tabela:
                self.tabelas.append((self.secao, self.tabela))
            self.tabela = None
        elif re.fullmatch(r"h[1-6]", tag) and self.em_heading:
            heading = _norm(" ".join(self.texto_heading))
            for nome, status in SECOES:
                if _norm(nome) in heading:
                    self.secao = status
                    break
            self.em_heading -= 1
            self.texto_heading = []


def _data(texto: str) -> date:
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%y").date()
    except ValueError as e:
        raise ErroPortal("última atualização inválida (DD/MM/AA)") from e


def extrair_lineup_portal(html: str, *, porto_id: str, fonte_url: str,
                          coletado_em: str, dias_validade: int = 7) -> dict:
    """Extrai tabela conhecida; não implica coleta online nem validade de licença."""
    if porto_id not in FONTES:
        raise ErroPortal("porto sem adaptador")
    host, prefixo = FONTES[porto_id]
    parsed = urlsplit(fonte_url)
    if (parsed.scheme != "https" or parsed.hostname != host or
            not parsed.path.startswith(prefixo) or parsed.username or parsed.password):
        raise ErroPortal("URL fora da fonte oficial declarada")
    if porto_id in {"SALVADOR", "ILHEUS"} and ("secao=tportos_"+porto_id.lower()) not in parsed.query:
        raise ErroPortal("seção CODEBA diferente do porto solicitado")
    if porto_id == "ARATU" and parsed.query != "secao=tportos_aratu":
        raise ErroPortal("seção CODEBA Aratu não verificada")
    if not isinstance(html, str) or not html.strip() or len(html) > 8_000_000:
        raise ErroPortal("HTML inválido")
    agora = instante(coletado_em)
    if not 1 <= dias_validade <= 15:
        raise ErroPortal("validade fora do intervalo")
    parser = _TabelasPorSecao()
    parser.feed(html)
    parser.close()
    registros = []
    marcados = 0
    for situacao, tabela in parser.tabelas:
        if situacao is None:
            continue
        cab = [_norm(x) for x in tabela[0]]
        idx = {}
        for i, col in enumerate(cab):
            chave = MAPA.get(col)
            if chave:
                if chave in idx:
                    raise ErroPortal("coluna obrigatória duplicada")
                idx[chave] = i
        obrigatorios = {"navio","carga","quantidade"}
        if not obrigatorios <= set(idx):
            continue
        # Exigir IMO ou DUV, não inventar escala distinta.
        if "imo" not in idx and "duv" not in idx:
            raise ErroPortal("tabela sem identificador de embarcação")
        marcados += 1
        for row in tabela[1:]:
            if len(row) != len(cab):
                raise ErroPortal("linha de dados divergente do cabeçalho")
            get = lambda campo: row[idx[campo]].strip() if campo in idx else ""
            navio = get("navio")
            if not navio or navio.lower().startswith("sem novas programações"):
                continue
            quantidade = get("quantidade")
            if quantidade and not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)*", quantidade):
                raise ErroPortal("quantidade inválida")
            texto_data = get("ultima_atualizacao")
            atualizacao = _data(texto_data) if texto_data else None
            if atualizacao and atualizacao > agora.date():
                raise ErroPortal("data da linha no futuro")
            situacao_linha = situacao
            if situacao_linha == "DESPACHADO":
                # navio despachado NÃO é automaticamente carga concluída.
                classe = "LINEUP_INFORMADO"
            else:
                classe = "LINEUP_INFORMADO"
            # Na CODEBA falta timestamp de atualização por linha; ETA não é publicação.
            data_suficiente = bool(atualizacao)
            recente = bool(atualizacao and (agora.date() - atualizacao) <= timedelta(days=dias_validade))
            registros.append({
                "porto_id": porto_id, "situacao": situacao_linha,
                "classe_evidencia": classe,
                "navio": navio, "imo": get("imo") or None, "duv": get("duv") or None,
                "mercadoria_original": get("carga"), "quantidade_fonte_texto": quantidade or None,
                "unidade_quantidade": "NAO_VERIFICADA",
                "toneladas_programadas": None, "toneladas_realizadas": None,
                "eta_fonte": get("eta") or None, "berco": get("berco") or None,
                "ultima_atualizacao_linha": atualizacao.isoformat() if atualizacao else None,
                "coletado_em": agora.isoformat(), "fonte_url": fonte_url,
                "publicado_em": None,
                "linha_recente_por_data": recente, "data_linha_existe": data_suficiente,
                "apto_briefing": False,
                "bloqueio": "DIREITOS_LAYOUT_UNIDADE_E_TIMESTAMP_PUBLICACAO_PENDENTES" if recente
                    else "ATUALIZACAO_AUSENTE_OU_ANTIGA",
            })
    if marcados == 0:
        raise ErroPortal("nenhuma tabela compatível com layout do porto")
    if not registros and "sem novas programações" not in html.lower():
        raise ErroPortal("tabela sem registros válidos; não afirmar zero navios")
    return {"porto_id": porto_id, "registros": registros,
            "tabelas_compatíveis": marcados, "coletado_em": agora.isoformat(),
            "status": "EXTRAIDO_NAO_HOMOLOGADO_NAO_PUBLICAVEL",
            "nota": "Quantidade sem unidade comprovada; datas de linha não equivalem a timestamp de publicação"}
