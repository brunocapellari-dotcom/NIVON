"""Ponte PAM/SIDRA 1612 -> evidência anual IVO, sem promover estimativa a verdade.

Consome SOMENTE bytes já capturados via normalizador sidra_pam e conferidos
com registro_snapshots do NIVON. A data de publicação não vem no JSON SIDRA:
sua presença no ledger é declaração, NÃO certificação externa da data.
Nenhum HTTP, coleta, escrita, conversão safra/mês ou treinamento real.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone
from hashlib import sha256
from math import isfinite

from .historico import Observacao
from .sidra_pam import normalizar_pam_1612, planejar_pam_1612


class ErroPontePAM(ValueError):
    pass


_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _utc(value: datetime | str, field: str) -> datetime:
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    except ValueError as exc:
        raise ErroPontePAM(f"{field}: instante inválido") from exc
    if not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() is None:
        raise ErroPontePAM(f"{field}: timezone obrigatório")
    return d.astimezone(timezone.utc)


def _snapshot(db: sqlite3.Connection, *, digest: str, coleta: datetime,
              ano: int, corte: datetime, tamanho: int) -> dict:
    if not isinstance(db, sqlite3.Connection):
        raise ErroPontePAM("registro de snapshots SQLite obrigatório")
    try:
        rows = db.execute(
            """SELECT s.dataset_id,s.fonte_id,s.sha256,s.bytes,s.mime,
                      s.schema_versao,s.competencia,s.referencia,s.publicacao,
                      s.tipo,s.evidencia_direitos,c.coletado_utc
               FROM nivon_snapshots s
               JOIN nivon_coletas c ON c.snapshot_id=s.id
               WHERE s.dataset_id='IBGE_PAM' AND s.sha256=?""",
            (digest,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise ErroPontePAM("registro de snapshots indisponível") from exc
    encontrados = []
    for row in rows:
        (ds, fonte, h, length, mime, schema, competencia, referencia,
         publicada, tipo, direitos, visto) = tuple(row)
        if (ds != "IBGE_PAM" or fonte != "IBGE" or h != digest
                or length != tamanho or mime != "application/json"
                or schema != "sidra_pam_1612_v1" or competencia != str(ano)
                or referencia != f"{ano}-12-31"
                or tipo not in ("SINTETICO", "REAL_AUTORIZADO")):
            continue
        observado = _utc(visto, "coleta do snapshot")
        if observado != coleta or observado > corte:
            continue
        if not isinstance(publicada, str):
            continue
        try:
            pub = date.fromisoformat(publicada)
        except ValueError:
            continue
        if pub > observado.date() or pub > corte.date():
            continue
        if (tipo == "REAL_AUTORIZADO" and not direitos
                or tipo == "SINTETICO" and direitos is not None):
            continue
        encontrados.append((pub, tipo, direitos))
    if len(encontrados) != 1:
        raise ErroPontePAM("snapshot ou publicação declarada não coincidem com arquivo e coleta")
    pub, tipo, direitos = encontrados[0]
    return {"publicacao_declarada": pub, "classe_registro": tipo,
            "direitos_ref": direitos}


def preparar_pam_anual_asof(*, payload: bytes, plano: dict,
        coletado_em: str, corte: datetime, registro_db: sqlite3.Connection,
        variavel_autorizada: str, produto_autorizado: str,
        unidade_autorizada: str = "Toneladas") -> dict:
    """Prepara candidata anual sem fingir que SIDRA informa dia de publicação.

    variavel_autorizada e produto_autorizado são IDs NUMÉRICOS já
    auditados fora do adaptador; não traduz nomes comerciais por heurística.
    O retorno NÃO é label realizado certificado, mesmo para PAM anual.
    """
    instante = _utc(corte, "corte")
    coleta = _utc(coletado_em, "coletado_em")
    if coleta > instante:
        raise ErroPontePAM("arquivo coletado depois do corte")
    if not isinstance(payload, bytes) or not payload:
        raise ErroPontePAM("payload original obrigatório")
    if not isinstance(plano, dict):
        raise ErroPontePAM("plano SIDRA obrigatório")
    if (plano.get("variavel") != variavel_autorizada
            or plano.get("categoria_c81") != produto_autorizado
            or not isinstance(unidade_autorizada, str)
            or not unidade_autorizada.strip() or len(unidade_autorizada) > 100):
        raise ErroPontePAM("produto/variável/unidade sem mapeamento explícito")
    # Contrato oficial do planejador SIDRA; não reconstitui endpoint externo.
    expected = planejar_pam_1612(
        municipio_ibge=plano.get("municipio_ibge"),
        ano=plano.get("ano"),
        codigo_produto_c81=produto_autorizado,
        codigo_variavel=variavel_autorizada)
    if expected != plano:
        raise ErroPontePAM("plano SIDRA adulterado")
    normalizado = normalizar_pam_1612(
        payload, plano=plano, coletado_em=coleta.isoformat())
    digest = sha256(payload).hexdigest()
    if normalizado["sha256_original"] != digest:
        raise ErroPontePAM("SHA do normalizador incompatível")
    snapshot = _snapshot(registro_db, digest=digest, coleta=coleta,
                         ano=plano["ano"], corte=instante,
                         tamanho=len(payload))
    dados = normalizado["observacoes"]
    if len(dados) != 1:
        raise ErroPontePAM("plano municipal exige exatamente um registro")
    item = dados[0]
    if (item["municipio_ibge"] != plano["municipio_ibge"]
            or item["ano_civil"] != plano["ano"]
            or item["variavel_sidra"] != variavel_autorizada
            or item["produto_categoria_c81"] != produto_autorizado
            or item["unidade_original"] != unidade_autorizada):
        raise ErroPontePAM("unidade, classificação ou escopo SIDRA divergentes")
    estado = item["estado_valor"]
    valor = item["valor"]
    if estado != "OBSERVADO_NUMERICO" or isinstance(valor, bool) or not isinstance(valor, (int, float)) or not isfinite(valor):
        # Não converter zero arredondado, marcador especial, sigilo ou
        # indisponibilidade em label numérico exato.
        return {
            "estado": "BLOQUEADO_MARCADOR_SIDRA",
            "motivo": estado,
            "hash_payload": digest, "competencia": str(plano["ano"]),
            "treino_real_autorizado": False, "label_final_certificado": False,
            "observacao": None,
        }
    # A natureza permanece INFORMADO. A publicação no JSON é None;
    # data no ledger não prova sua autenticidade no site oficial.
    observado = Observacao(
        fonte="IBGE", variavel=f"PAM_{variavel_autorizada}",
        produto=f"C81_{produto_autorizado}", regiao=f"MUN_{plano['municipio_ibge']}",
        unidade=unidade_autorizada, competencia=str(plano["ano"]),
        calendario="ANO_CIVIL", referencia=date(plano["ano"], 12, 31),
        publicacao=snapshot["publicacao_declarada"], coleta=coleta,
        valor=float(valor), natureza="INFORMADO", edicao=digest)
    return {
        "estado": "PAM_ANUAL_CANDIDATO_NAO_CERTIFICADO",
        "observacao": observado,
        "hash_payload": digest, "dataset_id": "IBGE_PAM",
        "tipo_snapshot": snapshot["classe_registro"],
        "fonte_publicacao": "DECLARACAO_LEDGER_NAO_CONFIRMADA_NO_JSON",
        "ano_civil": plano["ano"], "unidade_original": unidade_autorizada,
        "data_referencia": observado.referencia.isoformat(),
        "data_publicacao_declarada": observado.publicacao.isoformat(),
        "data_coleta": observado.coleta.isoformat(),
        "competencia": observado.competencia,
        "treino_real_autorizado": False,
        "label_final_certificado": False,
        "homologacao_externa_verificada": False,
        "limite": ("PAM anual municipal não é LSPA mensal, safra comercial "
                   "ou produção mensal. O tipo INFORMADO exige auditoria "
                   "estatística independente antes de qualquer uso como verdade."),
    }
