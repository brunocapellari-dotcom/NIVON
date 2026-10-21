"""Pré-homologação editorial determinística do NIVON, sem HTTP ou envio.

As provas de licença, publicação, sessão e disponibilidade são fornecidas por
sistemas de origem auditados; um True isolado não substitui a prova externa.
O relatório serve à revisão humana; nunca autoriza despacho por si só.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

TITULO = "RESUMO ESTRATÉGICO DO AGRONEGÓCIO"
GRUPOS = frozenset({
    "CHICAGO", "MERCADO_FISICO", "PECUARIA", "ICE",
    "ENERGIA", "CAMBIO", "FRETES", "NOTICIAS",
})
FECHAMENTOS = frozenset({"CHICAGO", "ICE", "CAMBIO"})
CORREDORES = frozenset({
    ("SORRISO", "MT", "RONDONOPOLIS", "MT"),
    ("SORRISO", "MT", "DOM AQUINO", "MT"),
    ("SINOP", "MT", "MIRITITUBA", "PA"),
    ("SORRISO", "MT", "PARANAGUA", "PR"),
    ("SORRISO", "MT", "SANTOS", "SP"),
    ("SORRISO", "MT", "UBERABA", "MG"),
})
ROTAS_PRIORITARIAS = frozenset({
    ("SORRISO", "MT", "RONDONOPOLIS", "MT"),
    ("SORRISO", "MT", "DOM AQUINO", "MT"),
    ("SINOP", "MT", "MIRITITUBA", "PA"),
})
_SHA = re.compile(r"^[a-f0-9]{64}$")


def _instante(valor: object) -> datetime:
    if not isinstance(valor, str) or "T" not in valor:
        raise ValueError("timestamp ISO com hora/fuso obrigatório")
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp ISO inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("fuso obrigatório")
    return d.astimezone(timezone.utc)


def _normal(valor: object) -> str:
    if not isinstance(valor, str):
        return ""
    return unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode().upper().strip()


def _numero(valor: object, *, positivo: bool = False) -> Decimal:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str, Decimal)):
        raise ValueError("número ausente/inválido")
    try:
        n = Decimal(str(valor))
    except InvalidOperation as exc:
        raise ValueError("número inválido") from exc
    if not n.is_finite() or (positivo and n <= 0):
        raise ValueError("número não finito/fora do domínio")
    return n


def _numero_presente(linha: str, numero: Decimal) -> bool:
    """Compara grafias brasileiras/internacionais sem aceitar prefixos parciais."""
    base = format(numero.normalize(), "f")
    inteiro, _, fracao = base.partition(".")
    inteiro_us = f"{int(inteiro):,}"
    inteiros = {inteiro, inteiro_us, inteiro_us.replace(",", ".")}
    possibilidades = set()
    for parte in inteiros:
        if fracao:
            possibilidades.add(parte + "." + fracao)
            possibilidades.add(parte + "," + fracao)
        else:
            possibilidades.update({parte, parte + ",00", parte + ".00"})
    padroes = [re.escape(p) for p in possibilidades]
    # Escalas financeiras como PTAX têm quatro casas mesmo quando o Decimal
    # normalizado termina em zero (ex.: 5.0600 == 5.06).
    if fracao:
        for parte in inteiros:
            padroes.extend(re.escape(parte) + sep + re.escape(fracao) + r"0*"
                           for sep in (r"\.", ","))
    return any(re.search(r"(?<![\d.,])" + p + r"(?![\d.,])", linha)
               for p in padroes)


def _origem(reg: dict, agora: datetime) -> None:
    """Contrato externo mínimo; os metadados não equivalem a homologação."""
    if (not isinstance(reg.get("fonte_id"), str) or not reg["fonte_id"]
            or reg.get("direitos_publicacao") is not True
            or not isinstance(reg.get("evidencia_direitos_id"), str)
            or not reg["evidencia_direitos_id"].strip()):
        raise ValueError("fonte ou direitos de publicação não comprovados")
    if not isinstance(reg.get("sha256_origem"), str) or not _SHA.fullmatch(reg["sha256_origem"]):
        raise ValueError("hash de origem ausente")
    publicacao = _instante(reg.get("publicado_em"))
    coleta = _instante(reg.get("coletado_em"))
    if publicacao > agora or coleta > agora:
        raise ValueError("publicação/coleta futura")
    if coleta < publicacao:
        raise ValueError("coleta anterior à publicação declarada")


def _url_chave(valor: object) -> str:
    if not isinstance(valor, str) or len(valor) > 2048:
        raise ValueError("URL inválida")
    try:
        p = urlsplit(valor)
        porta = p.port
    except ValueError as exc:
        raise ValueError("URL inválida") from exc
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or porta not in (None, 443) or "." not in p.hostname):
        raise ValueError("URL HTTPS pública obrigatória")
    parametros = sorted((k, v) for k, v in parse_qsl(p.query)
                        if not k.lower().startswith("utm_")
                        and k.lower() not in {"fbclid", "gclid"})
    return urlunsplit(("https", p.hostname.lower(), p.path.rstrip("/") or "/",
                       urlencode(parametros), ""))


def _verificar_noticia(item: dict, agora: datetime) -> tuple[str, str, str]:
    _origem(item, agora)
    if item.get("publicacao_original_verificada") is not True:
        raise ValueError("data original não verificada externamente")
    pub = _instante(item["publicado_em"])
    if not agora - timedelta(hours=24) <= pub <= agora:
        raise ValueError("notícia fora da janela móvel de 24 horas")
    titulo = item.get("titulo")
    evento = item.get("evento_id")
    if not isinstance(titulo, str) or len(titulo.strip()) < 8:
        raise ValueError("título incompleto")
    if not isinstance(evento, str) or not evento.strip():
        raise ValueError("identidade do acontecimento ausente")
    return _url_chave(item.get("url")), _normal(titulo), evento.strip()


def _verificar_cotacao(item: dict, agora: datetime, texto: str) -> str:
    _origem(item, agora)
    grupo = item.get("grupo")
    if grupo not in GRUPOS - {"NOTICIAS", "FRETES"}:
        raise ValueError("grupo econômico inválido")
    ref = _instante(item.get("referencia_em"))
    if ref > agora:
        raise ValueError("cotação com referência futura")
    if not all(isinstance(item.get(x), str) and item[x].strip()
               for x in ("titulo", "unidade", "competencia", "natureza")):
        raise ValueError("unidade, competência ou natureza ausente")
    if item["natureza"] not in {"OBSERVADO", "INDICATIVO"}:
        raise ValueError("natureza econômica incompatível")
    valor = _numero(item.get("valor"), positivo=True)
    if "variacao_pct" in item:
        anterior = _numero(item.get("valor_anterior"), positivo=True)
        percentual = _numero(item["variacao_pct"])
        calculado = (valor / anterior - 1) * 100
        if abs(calculado - percentual) > Decimal("0.05"):
            raise ValueError("variação percentual não reconcilia com preços")
    if grupo in FECHAMENTOS:
        sessao = item.get("sessao_fechamento")
        ultima = item.get("ultima_sessao_concluida")
        if (item.get("fechamento_confirmado") is not True
                or not isinstance(sessao, str) or not isinstance(ultima, str)
                or sessao != ultima or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sessao)):
            raise ValueError("último fechamento não comprovado por calendário/fonte")
        if ref.date().isoformat() != sessao:
            raise ValueError("sessão não coincide com data de referência")
    else:
        if item.get("periodo_identificado") is not True:
            raise ValueError("período do indicador não identificado")
    linhas = [linha for linha in texto.splitlines()
              if _normal(item["titulo"]) in _normal(linha)]
    referencia_br = ref.strftime("%d/%m/%Y")
    if not any(_normal(item["unidade"]) in _normal(linha)
               and _numero_presente(linha, valor)
               and (ref.date().isoformat() in linha or referencia_br in linha)
               for linha in linhas):
        raise ValueError("cotação/unidade/valor/data não reconciliam com texto")
    if item.get("classe_estatistica") == "MEDIA_AMOSTRAL_MUNICIPAL_REVENDA":
        if grupo != "ENERGIA" or item["natureza"] != "INDICATIVO" or item["unidade"] != "R$/L":
            raise ValueError("ANP: média amostral não é preço nacional nem negociação")
        try:
            inicio = date.fromisoformat(item["semana_inicio"])
            fim = date.fromisoformat(item["semana_fim"])
            postos = item["postos_pesquisados"]
            if ((fim - inicio).days != 6 or fim.isoformat() != item["competencia"]
                    or fim > _instante(item["publicado_em"]).date()
                    or type(postos) is not int or postos < 1):
                raise ValueError("semana ou amostra inconsistente")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ANP: competência/semana/quantidade de postos inválidas") from exc
        if not any(inicio.strftime("%d/%m") in linha
                   and fim.strftime("%d/%m") in linha
                   and f"{postos} postos" in linha for linha in linhas):
            raise ValueError("ANP: semana ou tamanho amostral divergente do texto")
    return grupo


def _verificar_frete(item: dict, agora: datetime, texto: str) -> tuple:
    _origem(item, agora)
    rota = tuple(_normal(item.get(k)) for k in
                 ("origem", "uf_origem", "destino", "uf_destino"))
    if rota not in CORREDORES:
        raise ValueError("corredor fora do escopo")
    if item.get("tipo") != "FRETE_ANUNCIADO":
        raise ValueError("frete não é anúncio individual")
    if not all(isinstance(item.get(k), str) and item[k].strip() for k in
               ("pickup_entity_id", "transportadora", "produto", "equipamento",
                "regime_pf_pj", "condicao_pedagio")):
        raise ValueError("ponto, transportadora ou condição comercial ausente")
    valor_frete = _numero(item.get("valor_rs_t"), positivo=True)
    ref_frete = _instante(item.get("referencia_em"))
    if ref_frete > agora:
        raise ValueError("frete futuro")
    volume = item.get("volume_t_dia")
    if volume is not None:
        _numero(volume, positivo=True)
        if item.get("classificacao_volume") not in {"OBSERVADO", "REFERENCIA", "ESTIMADO"}:
            raise ValueError("volume sem classificação")
        if (item.get("classificacao_volume") != "OBSERVADO"
                and item.get("volume_realizado") is True):
            raise ValueError("volume de referência apresentado como realizado")
    linhas = [linha for linha in texto.splitlines()
              if _normal(item["origem"]) in _normal(linha)
              and _normal(item["destino"]) in _normal(linha)]
    if not any(_numero_presente(linha, valor_frete)
               and (ref_frete.date().isoformat() in linha
                    or ref_frete.strftime("%d/%m/%Y") in linha)
               for linha in linhas):
        raise ValueError("corredor/valor/data de frete não reconciliam com texto")
    if volume is not None and not any(
            _numero_presente(linha, _numero(volume, positivo=True))
            for linha in linhas):
        raise ValueError("volume auditado ausente do corredor")
    if volume is not None and item["classificacao_volume"] != "OBSERVADO":
        if not any((f"VOLUME {item['classificacao_volume']}" in _normal(linha)
                    or f"VOLUME DE {item['classificacao_volume']}" in _normal(linha))
                   for linha in linhas):
            raise ValueError("volume de referência/estimado sem rótulo editorial")
    return rota


def avaliar_previa_editorial(*, edicao: dict, gerado_em: str,
                            noticias: list[dict], cotacoes: list[dict],
                            fretes: list[dict]) -> dict:
    """Pré-publicação fail-closed, sem efeito colateral nem autorização de envio.

    Retorna bloqueios e lacunas; os campos de prova são declarações externas
    que dependem de validação independente na homologação operacional.
    """
    bloqueios: list[str] = []
    lacunas: list[str] = []
    try:
        agora = _instante(gerado_em)
    except ValueError:
        return {"apto_revisao": False, "bloqueios": ["GERACAO_SEM_FUSO"],
                "lacunas": [], "modo": "OFFLINE_SEM_ENVIO"}
    if not isinstance(edicao, dict):
        edicao = {}
    texto = edicao.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        texto = ""
        bloqueios.append("TEXTO_AUSENTE")
    if (edicao.get("estado") != "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO"
            or edicao.get("enviado") is not False):
        bloqueios.append("ESTADO_EDICAO_INVALIDO")
    try:
        if _instante(edicao.get("gerado_em")) != agora:
            bloqueios.append("DATA_EDICAO_DIVERGENTE")
    except ValueError:
        bloqueios.append("DATA_EDICAO_INVALIDA")
    if edicao.get("sha256") != hashlib.sha256(texto.encode("utf-8")).hexdigest():
        bloqueios.append("SHA_TEXTO_DIVERGENTE")
    if TITULO not in texto.upper():
        bloqueios.append("TITULO_EDITORIAL_INCORRETO")
    if re.search(r"(?im)^\s*(?:[▶️*#\s]*)?(?:POSSÍVEL IMPACTO|IMPACTOS(?:\s|:)|RESUMO EXECUTIVO|MONITORAR(?:\s|:))", texto):
        bloqueios.append("SECAO_EDITORIAL_PROIBIDA")

    if not isinstance(noticias, list) or not noticias:
        bloqueios.append("SEM_NOTICIAS_VERIFICADAS")
        noticias = []
    chaves: set[str] = set()
    titulos: set[str] = set()
    eventos: set[str] = set()
    for i, item in enumerate(noticias):
        try:
            if not isinstance(item, dict):
                raise ValueError("notícia não estruturada")
            url, titulo, evento = _verificar_noticia(item, agora)
            if url in chaves or titulo in titulos or evento in eventos:
                raise ValueError("notícia duplicada ou acontecimento repetido")
            chaves.add(url)
            titulos.add(titulo)
            eventos.add(evento)
            if titulo not in _normal(texto):
                raise ValueError("notícia auditada ausente do texto")
        except (ValueError, KeyError, TypeError) as exc:
            bloqueios.append(f"NOTICIA_{i}:{exc}")

    vistos = set()
    if not isinstance(cotacoes, list):
        bloqueios.append("COTACOES_INVALIDAS")
        cotacoes = []
    for i, item in enumerate(cotacoes):
        try:
            if not isinstance(item, dict):
                raise ValueError("cotação não estruturada")
            grupo = _verificar_cotacao(item, agora, texto)
            chave = (grupo, item["titulo"], item["referencia_em"])
            if chave in vistos:
                raise ValueError("cotação repetida")
            vistos.add(chave)
        except (ValueError, KeyError, TypeError) as exc:
            bloqueios.append(f"COTACAO_{i}:{exc}")
    if not cotacoes:
        bloqueios.append("SEM_COTACOES_AUDITADAS")
    grupos = {x[0] for x in vistos}
    lacunas.extend("SEM_COTACAO:" + grupo for grupo in sorted(
        GRUPOS - {"NOTICIAS", "FRETES"} - grupos))

    if not isinstance(fretes, list):
        bloqueios.append("FRETES_INVALIDOS")
        fretes = []
    rotas = set()
    for i, item in enumerate(fretes):
        try:
            if not isinstance(item, dict):
                raise ValueError("frete não estruturado")
            rotas.add(_verificar_frete(item, agora, texto))
        except (ValueError, KeyError, TypeError) as exc:
            bloqueios.append(f"FRETE_{i}:{exc}")
    if not fretes:
        bloqueios.append("SEM_FRETES_AUDITADOS")
    for rota in sorted(ROTAS_PRIORITARIAS - rotas):
        lacunas.append("CORREDOR_SEM_DADO_VALIDO:" + "/".join(rota))
    return {"apto_revisao": not bloqueios,
            "bloqueios": bloqueios, "lacunas": lacunas,
            "quantidades": {"noticias": len(noticias), "cotacoes": len(cotacoes),
                            "fretes": len(fretes)},
            "sha256_texto": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
            "modo": "OFFLINE_SEM_ENVIO",
            "nota": "Apto à revisão não é autorizado para publicação nem prova direitos."}
