"""CONAB: disponibilidade histórica auditável, sem falsear data de coleta.

Acrescenta um sidecar ao SQLite CONAB existente. Não altera o parser, não
importa outro warehouse e não retrodata snapshots. Só libera 'as-of'
anterior à coleta se a evidência documental tiver sido aprovada explicitamente.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from .transacoes_sqlite import savepoint_atomico

SHA = re.compile(r"^[a-f0-9]{64}$")
_ARQ = re.compile(r"^(?:SojaSerieHist|Milho(?:1a|2a|3a|Total)SerieHist)\.xls$")
VERIFICACAO = frozenset({"PENDENTE_AUDITORIA", "HOMOLOGADA", "REVOGADA"})


class ErroVintageConab(ValueError):
    pass


def _date(valor: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        raise ErroVintageConab("data deve ser YYYY-MM-DD")
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError as exc:
        raise ErroVintageConab("data impossível") from exc


def _utc(valor: str) -> str:
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ErroVintageConab("instante ISO inválido") from exc
    if instante.utcoffset() is None:
        raise ErroVintageConab("instante sem timezone")
    return instante.astimezone(timezone.utc).isoformat()


def _url_conab(url: str) -> str:
    if not isinstance(url, str) or len(url) > 1800:
        raise ErroVintageConab("URL de evidência inválida")
    uri = urlsplit(url)
    if (uri.scheme != "https" or uri.hostname not in {"www.gov.br", "www.conab.gov.br"}
            or uri.port not in (None, 443) or uri.username or uri.password or uri.fragment):
        raise ErroVintageConab("documento de evidência deve estar em URL HTTPS oficial")
    if uri.hostname == "www.gov.br" and not uri.path.startswith("/conab/"):
        raise ErroVintageConab("domínio GOV.BR não aponta para a CONAB")
    return url


def _schema(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS conab_disponibilidade_historica(
          fonte_sha TEXT NOT NULL,
          arquivo TEXT NOT NULL,
          disponivel_em TEXT NOT NULL,
          evidencia_url TEXT NOT NULL,
          evidencia_sha256 TEXT NOT NULL,
          registrado_em TEXT NOT NULL,
          homologado_em TEXT,
          verificador TEXT,
          status TEXT NOT NULL CHECK(status IN
            ('PENDENTE_AUDITORIA','HOMOLOGADA','REVOGADA')),
          PRIMARY KEY(fonte_sha,arquivo),
          FOREIGN KEY(fonte_sha,arquivo)
            REFERENCES conab_edicoes(fonte_sha,arquivo)
        )
    """)


def registrar_evidencia(db, *, fonte_sha: str, arquivo: str,
                       disponivel_em: str, evidencia_url: str,
                       evidencia_sha256: str, registrado_em: str) -> dict:
    """Registra metadados do documento. NÃO libera cutoff histórico."""
    if not isinstance(fonte_sha, str) or not SHA.fullmatch(fonte_sha):
        raise ErroVintageConab("hash da edição inválido")
    if not isinstance(arquivo, str) or not _ARQ.fullmatch(arquivo):
        raise ErroVintageConab("arquivo histórico CONAB não suportado")
    if not isinstance(evidencia_sha256, str) or not SHA.fullmatch(evidencia_sha256):
        raise ErroVintageConab("hash da evidência ausente")
    data = _date(disponivel_em)
    url = _url_conab(evidencia_url)
    registrado = _utc(registrado_em)
    row = db.execute(
        """SELECT e.publicado_em, MIN(c.coletado_utc) AS primeira_coleta
           FROM conab_edicoes e JOIN conab_coletas c USING(fonte_sha,arquivo)
           WHERE e.fonte_sha=? AND e.arquivo=? GROUP BY e.fonte_sha,e.arquivo""",
        (fonte_sha,arquivo)).fetchone()
    if row is None or row["primeira_coleta"] is None:
        raise ErroVintageConab("edição sem RAW/observação no store NIVON")
    pub = row["publicado_em"]
    if pub is None:
        raise ErroVintageConab("não retroceder cutoff sem data da publicação CONAB")
    if not pub <= data <= row["primeira_coleta"][:10]:
        raise ErroVintageConab("disponibilidade inconsistente com publicação/coleta")
    if registrado < row["primeira_coleta"]:
        raise ErroVintageConab("registro da evidência não pode preceder coleta")
    _schema(db)
    with savepoint_atomico(db):
        old = db.execute(
            "SELECT * FROM conab_disponibilidade_historica WHERE fonte_sha=? AND arquivo=?",
            (fonte_sha,arquivo)).fetchone()
        if old:
            if (old["disponivel_em"],old["evidencia_url"],old["evidencia_sha256"]) != (
                    data,url,evidencia_sha256):
                raise ErroVintageConab("evidência conflitante: não substituir silenciosamente")
            return {"registrada":False,"estado":old["status"]}
        db.execute(
            "INSERT INTO conab_disponibilidade_historica VALUES(?,?,?,?,?,?,NULL,NULL,?)",
            (fonte_sha,arquivo,data,url,evidencia_sha256,registrado,
             "PENDENTE_AUDITORIA"))
    return {"registrada":True,"estado":"PENDENTE_AUDITORIA"}


def homologar_evidencia(db, *, fonte_sha: str, arquivo: str,
                       evidencia_sha256: str, verificador: str,
                       homologado_em: str, documento_conferido: bool = False) -> dict:
    """Aprovação documental explícita após verificar o original fora do sistema.

    O método não faz HTTP nem valida autonomamente a veracidade do PDF.
    """
    if documento_conferido is not True:
        raise ErroVintageConab("documento de publicação não conferido")
    if not isinstance(verificador, str) or not 6 <= len(verificador.strip()) <= 100:
        raise ErroVintageConab("verificador e critério de revisão obrigatórios")
    at = _utc(homologado_em)
    _schema(db)
    with savepoint_atomico(db):
        old = db.execute(
            "SELECT * FROM conab_disponibilidade_historica WHERE fonte_sha=? AND arquivo=?",
            (fonte_sha,arquivo)).fetchone()
        if old is None or old["evidencia_sha256"] != evidencia_sha256:
            raise ErroVintageConab("evidência não localizada ou hash divergente")
        if old["status"] == "REVOGADA":
            raise ErroVintageConab("evidência revogada: abrir nova revisão documentada")
        if at < old["registrado_em"]:
            raise ErroVintageConab("homologação anterior ao registro da evidência")
        if old["status"] == "HOMOLOGADA":
            return {"homologada":False,"estado":"HOMOLOGADA"}
        db.execute(
            """UPDATE conab_disponibilidade_historica
               SET status='HOMOLOGADA',homologado_em=?,verificador=?
               WHERE fonte_sha=? AND arquivo=?""",
            (at,verificador,fonte_sha,arquivo))
    return {"homologada":True,"estado":"HOMOLOGADA"}


def revogar_evidencia(db, *, fonte_sha: str, arquivo: str) -> None:
    """Revogação não remove dados históricos, mas bloqueia retrodatação."""
    _schema(db)
    with savepoint_atomico(db):
        row = db.execute("SELECT 1 FROM conab_disponibilidade_historica "
                         "WHERE fonte_sha=? AND arquivo=?",(fonte_sha,arquivo)).fetchone()
        if row is None:
            raise ErroVintageConab("evidência inexistente")
        db.execute("UPDATE conab_disponibilidade_historica SET status='REVOGADA' "
                   "WHERE fonte_sha=? AND arquivo=?",(fonte_sha,arquivo))


def consultar_historico_asof(db, *, corte_utc: str, arquivo: str,
                             uf: str, indicador: str, safra: str) -> dict | None:
    """Retorna somente o que podia ser conhecido no instante de corte.

    Mesmo que dados fossem publicados em 2025 e coletados em 2026,
    só ficam visíveis em 2025 com prova documental homologada.
    """
    cutoff = _utc(corte_utc)
    _schema(db)
    dados = db.execute("""
      SELECT o.valor,o.unidade,o.classe,o.fonte_sha,o.arquivo,
             e.publicado_em, MIN(c.coletado_utc) AS primeira_coleta,
             dh.disponivel_em,dh.status AS evidencia_status
        FROM conab_observacoes o
        JOIN conab_edicoes e USING(fonte_sha,arquivo)
        JOIN conab_coletas c USING(fonte_sha,arquivo)
        LEFT JOIN conab_disponibilidade_historica dh USING(fonte_sha,arquivo)
       WHERE o.arquivo=? AND o.uf=? AND o.indicador=? AND o.safra=?
       GROUP BY o.fonte_sha,o.arquivo,o.uf,o.safra,o.indicador
    """,(arquivo,uf,indicador,safra)).fetchall()
    elegiveis=[]
    for r in dados:
        pub=r["publicado_em"]
        if pub is not None and pub > cutoff[:10]:
            continue
        coletado = r["primeira_coleta"] <= cutoff
        validada = (r["evidencia_status"] == "HOMOLOGADA"
                    and pub is not None
                    and r["disponivel_em"] is not None
                    and r["disponivel_em"] <= cutoff[:10])
        if not coletado and not validada:
            continue
        evid_tipo = "DOCUMENTO_HOMOLOGADO" if validada and not coletado else "COLETA_OBSERVADA"
        elegiveis.append((r, evid_tipo))
    if not elegiveis:
        return None
    elegiveis.sort(
        key=lambda pair: (pair[0]["publicado_em"] or "", pair[0]["primeira_coleta"]),
        reverse=True)
    primeiro,evidencia = elegiveis[0]
    # Se duas edições são atribuídas à mesma data de publicação e ambas
    # elegíveis, não inventar qual era a versão corrente no passado.
    ambiguos=[r for r,_ in elegiveis
              if r["publicado_em"] == primeiro["publicado_em"] and
                 r["fonte_sha"] != primeiro["fonte_sha"]]
    if ambiguos:
        return {"status":"AMBIGUO_VINTAGE_MESMA_PUBLICACAO",
                "edicoes_conflitantes":len(ambiguos)+1,"valor":None}
    return {
        "status":"DISPONIVEL_ASOF",
        "valor":primeiro["valor"],"unidade":primeiro["unidade"],
        "classe":primeiro["classe"],"fonte_sha":primeiro["fonte_sha"],
        "arquivo":primeiro["arquivo"],"data_publicacao":primeiro["publicado_em"],
        "primeira_coleta":primeiro["primeira_coleta"],
        "disponivel_em_documentada":primeiro["disponivel_em"] if evidencia=="DOCUMENTO_HOMOLOGADO" else None,
        "criterio_cutoff":evidencia,
        "data_coleta_retrodatada":False,
    }
