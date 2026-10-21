"""Leitura isolada de uma captura XLS CONAB aprovada apenas quanto a bytes/link.

Não faz rede, não persiste RAW e nunca certifica divulgação histórica.
O pacote opcional xlrd deve processar bytes não confiáveis em worker isolado,
com memória/tempo limitados pelo executor, nunca no processo principal.
"""
from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
import re

from .conab_series import (
    UF, ARQUIVOS, normalizar_livro, ErroConab,
)
from .auditoria_conab_pam import (
    preparar_tripla_conab, ErroConciliacaoSafra,
)

_OLE = bytes.fromhex("d0cf11e0a1b11ae1")
_ANO = re.compile(r"((?:19|20)\d{2})/((?:19|20)\d{2})\Z")


class ErroLeituraXLSConab(ValueError):
    """RAW ou livro não satisfazem os contratos de layout e proveniência."""


def _abrir_livro(raw: bytes):
    """xlrd é opt-in: .xls binário apenas; macros nunca são executadas."""
    try:
        import xlrd
    except ImportError as exc:
        raise ErroLeituraXLSConab(
            "xlrd ausente: instalar o extra excel_conab em worker isolado"
        ) from exc
    return xlrd.open_workbook(
        file_contents=raw, on_demand=True, formatting_info=False,
    )


def inspecionar_xls_conab_capturado(
    *, manifesto_raw: dict, planilha_raw: bytes, uf: str, safra: str,
    emitido_em: str,
) -> dict:
    """Valida layout CONAB e extrai uma tripla física, sem afirmar edição.

    O manifesto provém de verificar_raw_conab. O SHA é recalculado sobre
    planilha_raw e não basta confiança em campos declarativos do manifesto.
    O decoder XLS é opcional, mas sem ele ocorre erro, nunca sucesso falso.
    """
    if not isinstance(manifesto_raw, dict) or manifesto_raw.get("status") != (
            "CAPTURA_SHA_OLE2_LINK_SEM_VALIDACAO_XLS_OU_VINTAGE"):
        raise ErroLeituraXLSConab("manifesto de captura CONAB não reconhecido")
    meta = manifesto_raw.get("snapshot_meta")
    arquivo = manifesto_raw.get("arquivo")
    cultura = manifesto_raw.get("cultura")
    if (arquivo not in ARQUIVOS or ARQUIVOS[arquivo][0] != cultura or
            manifesto_raw.get("subdivisao_safra") != ARQUIVOS[arquivo][1]):
        raise ErroLeituraXLSConab("arquivo/cultura/subdivisão incongruentes")
    if (not isinstance(meta, dict) or meta.get("fonte_id") != "CONAB" or
            meta.get("edicao_id") != "DESCONHECIDA" or
            meta.get("disponibilidade_verificada") is not False or
            meta.get("publicado_em") is not None or
            meta.get("disponivel_em") is not None or
            meta.get("prova_disponibilidade_sha256") is not None):
        raise ErroLeituraXLSConab("a captura não prova edição ou disponibilidade PIT")
    for flag in ("estrutura_xls_validada", "abas_xls_lidas",
                 "vintage_asof_comprovada", "habilita_backtest",
                 "habilita_treino", "habilita_publicacao"):
        if manifesto_raw.get(flag) is not False:
            raise ErroLeituraXLSConab("manifesto alterou gate de segurança: " + flag)
    if (not isinstance(planilha_raw, bytes) or
            not 512 <= len(planilha_raw) <= 30_000_000 or
            not planilha_raw.startswith(_OLE)):
        raise ErroLeituraXLSConab("XLS bruto inválido")
    digest = sha256(planilha_raw).hexdigest()
    esperados = (meta.get("raw_sha256"),
                 manifesto_raw.get("xls_raw_sha256"))
    if any(not isinstance(d, str) or not compare_digest(digest, d)
           for d in esperados):
        raise ErroLeituraXLSConab("XLS não corresponde ao SHA da captura")
    if manifesto_raw.get("tamanho_xls_bytes") != len(planilha_raw):
        raise ErroLeituraXLSConab("tamanho bruto diverge do manifesto")
    if not isinstance(uf, str) or uf not in UF:
        raise ErroLeituraXLSConab("UF fora do catálogo CONAB")
    m = _ANO.fullmatch(safra) if isinstance(safra, str) else None
    if not m or int(m[2]) != int(m[1]) + 1:
        raise ErroLeituraXLSConab("safra normalizada AAAA/AAAA obrigatória")
    if not isinstance(meta.get("coletado_em"), str):
        raise ErroLeituraXLSConab("data real de coleta ausente")
    if meta["coletado_em"] != manifesto_raw.get("coletado_xls_em"):
        raise ErroLeituraXLSConab("coleta da captura divergente")
    livro = None
    try:
        # O executor deve isolar parsing de arquivos não confiáveis. Este
        # método não oferece nem simula sandbox ou limites de processo.
        livro = _abrir_livro(planilha_raw)
        observacoes = normalizar_livro(
            livro, arquivo, sha256=digest, capturado_em=meta["coletado_em"],
        )
    except (ErroConab, ErroLeituraXLSConab) as exc:
        raise ErroLeituraXLSConab("XLS não validado: " + str(exc)) from exc
    except Exception as exc:
        # Inclui corrupção de arquivo e exceções internas do parser; não
        # liberar parcialmente uma leitura incompleta.
        raise ErroLeituraXLSConab("parser XLS falhou; captura rejeitada") from exc
    finally:
        if livro is not None:
            try:
                release = getattr(livro, "release_resources", None)
                if callable(release):
                    release()
            except Exception:
                pass

    selecionados = [
        x for x in observacoes
        if x["regiao_uf"] == uf and x["safra"] == safra
    ]
    if len(selecionados) != 3 or len({x["indicador"] for x in selecionados}) != 3:
        raise ErroLeituraXLSConab(
            "tripla AREA/PRODUTIVIDADE/PRODUCAO ausente ou incompleta"
        )
    try:
        tripla = preparar_tripla_conab(
            linhas=selecionados, uf=uf, cultura=cultura,
            subdivisao=ARQUIVOS[arquivo][1], safra=safra,
            snapshot_meta=meta, emitido_em=emitido_em,
        )
    except ErroConciliacaoSafra as exc:
        raise ErroLeituraXLSConab("tripla física CONAB reprovada") from exc
    if tripla["estado"] != "TRIPLA_CONAB_SEM_PROVA_ASOF":
        raise ErroLeituraXLSConab("captura sem edição foi promovida indevidamente")
    return {
        "status": "XLS_DECODIFICADO_E_NORMALIZADO_SEM_VINTAGE_ASOF",
        "cultura": cultura, "subdivisao_safra": ARQUIVOS[arquivo][1],
        "arquivo": arquivo, "safra": safra, "uf": uf,
        "raw_sha256": digest,
        "estrutura_xls_validada": True,  # apenas estrutura decodificada
        "abas_xls_lidas": True,
        "observacoes_total_normalizadas": len(observacoes),
        "cabecalhos_inferidos_no_recorte": sum(
            bool(x["rotulo_coluna_inferido"]) for x in selecionados
        ),
        "celulas_origem": {
            x["indicador"]: x["celula"] for x in selecionados
        },
        "tripla_fisica": tripla,
        "quantidade_realizada_comprovada": False,
        "edicao_historica_comprovada": False,
        "vintage_asof_comprovada": False,
        "habilita_backtest": False,
        "habilita_treino": False,
        "habilita_publicacao": False,
    }
