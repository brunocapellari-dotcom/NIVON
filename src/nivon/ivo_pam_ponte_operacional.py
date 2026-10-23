"""PAM/IVO: concilia banco operacional de capturas com auditoria e revisão.

O histórico SQLite do piloto SIDRA é STAGING: pode conter capturas reais,
mas não prova qual versão foi publicada em cada ano. Este adaptador é
read-only e nunca move conteúdo para o ledger canônico.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .ivo_pam_gate_promocao import REQUISITOS
from .ivo_pam_pacote_auditoria import preparar_pacote_pam_quarentena
from .ivo_pam_qualidade import auditar_operacao_pam
from .sidra_pam import planejar_pam_1612


class ErroPonteOperacionalPAM(ValueError):
    pass


def _canon(obj: object) -> bytes:
    try:
        data = json.dumps(
            obj, sort_keys=True, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ErroPonteOperacionalPAM("conteudo nao serializavel") from exc
    if len(data) > 2_000_000:
        raise ErroPonteOperacionalPAM("pacote excede tamanho")
    return data


def _sha(obj: object) -> str:
    return hashlib.sha256(_canon(obj)).hexdigest()


def _instante(v: object) -> datetime:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroPonteOperacionalPAM("data de captura invalida") from exc
    if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroPonteOperacionalPAM("data UTC com fuso necessaria")
    return v.astimezone(timezone.utc)


def revisar_capturas_pam(
    *, db: sqlite3.Connection, raiz: str | Path,
    corte_coleta: datetime | None = None, max_capturas: int = 1000,
) -> dict:
    """Confere integralmente staging + quarentena e monta fila por vintage.

    Cada linha de captura (não cada ano) tem recibo de custódia local.
    Datas as-of são de COLETA, não da publicação anual do IBGE.
    Se um objeto do DB falhar validação, nenhuma revisão parcial é emitida.
    """
    if (not isinstance(db, sqlite3.Connection) or
            type(max_capturas) is not int or not 1 <= max_capturas <= 3000):
        raise ErroPonteOperacionalPAM("parametros de revisao invalidos")
    corte = _instante(corte_coleta) if corte_coleta is not None else None
    try:
        check = auditar_operacao_pam(db=db, raiz=raiz, max_vintages=max_capturas)
    except (sqlite3.Error, ValueError, OSError) as exc:
        raise ErroPonteOperacionalPAM("auditoria SQLite/quarentena indisponivel") from exc
    if (check["estado"] != "INTEGRIDADE_LOCAL_VERIFICADA"
            or check["integridade_local_aprovada"] is not True):
        raise ErroPonteOperacionalPAM("integridade do acervo operacional falhou")
    try:
        db.row_factory = sqlite3.Row
        rows = db.execute("""SELECT v.municipio, v.ano, v.variavel,
            v.produto, v.sha256, v.recibo_sha256,
            c.coletado_em, c.mudanca, c.origem
            FROM pam_vintages v JOIN pam_capturas c
              ON v.municipio=c.municipio AND v.ano=c.ano
             AND v.variavel=c.variavel AND v.produto=c.produto
             AND v.sha256=c.sha256
            ORDER BY c.coletado_em, v.municipio, v.ano, v.variavel,
                     v.produto, v.sha256
            LIMIT ?""", (max_capturas + 1,)).fetchall()
    except sqlite3.Error as exc:
        raise ErroPonteOperacionalPAM("schema SQLite operacional invalido") from exc
    if len(rows) > max_capturas:
        raise ErroPonteOperacionalPAM("excesso de capturas; particionar consulta")
    itens = []
    chaves = set()
    for r in rows:
        data = _instante(r["coletado_em"])
        if corte is not None and data > corte:
            continue
        key = (r["municipio"], r["ano"], r["variavel"],
               r["produto"], r["sha256"], data.isoformat())
        if key in chaves:
            raise ErroPonteOperacionalPAM("captura duplicada na revisao")
        chaves.add(key)
        try:
            plano = planejar_pam_1612(
                municipio_ibge=r["municipio"], ano=r["ano"],
                codigo_produto_c81=r["produto"],
                codigo_variavel=r["variavel"],
            )
            pacote = preparar_pacote_pam_quarentena(
                raiz=raiz, recibo_sidra=r["recibo_sha256"], plano=plano,
            )
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise ErroPonteOperacionalPAM(
                "captura sem comprovacao local consistente"
            ) from exc
        # A prova referencia apenas o recibo preservado (da primeira
        # captura deste SHA). Recoletas iguais nao ganham comprovacao falsa
        # de horario de publicacao ou coleta historica.
        if (pacote["json_sha256"] != r["sha256"] or
                pacote["recibo_json_sha256"] != r["recibo_sha256"] or
                pacote["municipio_ibge"] != r["municipio"] or
                pacote["ano_civil"] != r["ano"] or
                pacote["categoria_c81"] != r["produto"]):
            raise ErroPonteOperacionalPAM("metadados SQL e dossie divergem")
        itens.append({
            "municipio_ibge": r["municipio"],
            "ano_civil": r["ano"],
            "variavel_sidra": r["variavel"],
            "categoria_c81": r["produto"],
            "sha256_original": r["sha256"],
            "recibo_sha256": r["recibo_sha256"],
            "coletado_em": data.isoformat(),
            "origem_declarada": r["origem"],
            "mudanca_operacional": r["mudanca"],
            "auditoria_sha256": _sha(pacote),
            "bloqueios_locais": sorted(set(pacote["bloqueios"])),
            "requisitos_externos_pendentes": list(REQUISITOS),
            "estado": "CAPTURA_OPERACIONAL_REVISADA_SEM_HOMOLOGACAO",
            "liberado_para_promocao": False,
        })
    movimentos = ("VALOR_ALTERADO", "ESTADO_ALTERADO", "NOVOS_BYTES_MESMO_VALOR")
    body = {
        "schema": "nivon_ivo_pam_ponte_operacional_v1",
        "estado": "FILA_DE_REVISAO_OPERACIONAL_SEM_PROMOCAO",
        "corte_coleta": corte.isoformat() if corte else None,
        "capturas_sqlite_totais": check["capturas_registradas"],
        "capturas_consideradas": len(itens),
        "versoes_sqlite_auditadas": check["vintages_verificadas"],
        "mudancas_observadas": sum(x["mudanca_operacional"] in movimentos
                                 for x in itens),
        "itens": itens,
        "dados_reais_homologados": False,
        "publicacao_oficial_comprovada": False,
        "liberado_para_treino": False,
        "ledger_canonico_modificado": False,
        "permissao_publicacao_concedida": False,
        "aviso": ("Vintages e capturas verificadas por hash LOCAL. "
                  "Coleta nao equivale a data de publicacao; dados "
                  "continuam pendentes de revisao externa."),
    }
    return {**body, "manifesto_sha256": _sha(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audita SQLite PAM e gera fila imutavel de revisao (sem rede)"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--acervo", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--corte", default=None)
    args = parser.parse_args(argv)
    try:
        path = args.db.expanduser()
        if path.is_symlink() or not path.is_file():
            raise ErroPonteOperacionalPAM("SQLite operacional ausente")
        # mode=ro impede criar banco se o caminho estiver errado.
        uri = "file:" + quote(str(path.resolve(strict=True)), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as db:
            db.execute("PRAGMA query_only=ON")
            outcome = revisar_capturas_pam(
                db=db, raiz=args.acervo,
                corte_coleta=_instante(args.corte) if args.corte else None,
            )
        out = args.saida.expanduser()
        if out.parent.is_symlink() or not out.parent.is_dir() or out.is_symlink():
            raise ErroPonteOperacionalPAM("pasta de destino invalida")
        encoded = (json.dumps(outcome, sort_keys=True, ensure_ascii=False,
                              indent=2) + "\n").encode("utf-8")
        try:
            with out.open("xb") as handle:
                handle.write(encoded)
        except FileExistsError:
            if out.read_bytes() != encoded:
                raise ErroPonteOperacionalPAM("relatorio existente divergente")
        print(json.dumps({
            "estado": outcome["estado"],
            "capturas_consideradas": outcome["capturas_consideradas"],
            "mudancas_observadas": outcome["mudancas_observadas"],
            "manifesto_sha256": outcome["manifesto_sha256"],
            "promocoes": 0,
        }, sort_keys=True))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"estado": "ERRO_REVISAO_OPERACIONAL",
                          "erro_classe": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
