"""Pacote SOMENTE LEITURA de auditoria da quarentena PAM/SIDRA do NIVON.

Confere SHA-256 dos bytes e recibos, URL canônica, identidade da célula
municipal, cultura/variável/unidade e evidencia ausências documentais.
NÃO atesta download, autoria IBGE, data oficial de publicação ou licença;
não insere no registro_snapshots nem autoriza treinamento.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .ivo_pam_quarentena import conferir_recibo_pam, ErroQuarentenaPAM
from .ivo_pam_coletor_pontual import _url
from .ivo_pam_semantica import conferir_semantica_pam_1612, ErroSemanticaPAM
from .sidra_pam import (
    planejar_pam_1612, normalizar_pam_1612, ErroSIDRAPAM,
)


class ErroPacotePAM(ValueError):
    pass


_HASH = re.compile(r"[a-f0-9]{64}\Z")


def _instante(value, campo):
    if not isinstance(value, str):
        raise ErroPacotePAM(f"{campo}: data ausente")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPacotePAM(f"{campo}: data inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroPacotePAM(f"{campo}: fuso obrigatório")
    return dt.astimezone(timezone.utc)


def _arquivo_recibo(raiz, digest):
    if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
        raise ErroPacotePAM("hash de recibo inválido")
    # A quarentena verifica, antes da leitura de qualquer dado, o recibo
    # e o SHA real dos bytes do objeto. Sem promover para dado oficial.
    try:
        validado = conferir_recibo_pam(raiz=raiz, recibo_sha256=digest)
    except ErroQuarentenaPAM as exc:
        raise ErroPacotePAM("recibo ou objeto da quarentena não íntegro") from exc
    root = Path(raiz).expanduser()
    recibo = root / "recibos" / (digest + ".json")
    if recibo.is_symlink() or not recibo.is_file() or recibo.stat().st_size > 5000:
        raise ErroPacotePAM("recibo inválido ou acima do tamanho permitido")
    raw = recibo.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ErroPacotePAM("recibo mudou durante a leitura")
    try:
        meta = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ErroPacotePAM("manifesto ilegível") from exc
    if (not isinstance(meta, dict) or meta.get("schema") != "nivon_ivo_pam_quarentena_v1"
            or meta.get("sha256") != validado["sha256"]
            or meta.get("bytes") != validado["bytes"]
            or meta.get("dataset_id") != "IBGE_PAM" or meta.get("fonte") != "IBGE"
            or any(meta.get(flag) is not False for flag in (
                "fonte_autenticada_externamente", "data_publicacao_atestada",
                "direitos_validados_externamente", "liberado_para_treino",
                "inscrito_no_ledger_canonico"))):
        raise ErroPacotePAM("manifesto não corresponde a candidato bloqueado")
    especie = meta.get("tipo")
    try:
        origem = _url(meta.get("url_declarada"), tipo=especie)
    except ValueError as exc:
        raise ErroPacotePAM("endereço de fonte incoerente") from exc
    if not isinstance(meta.get("referencia_direitos_declarada"), str):
        raise ErroPacotePAM("referência de direitos ausente")
    capturado = _instante(meta.get("captura_declarada_em"), "captura")
    objeto = root / "objetos_sha256" / (validado["sha256"] + ".bin")
    if objeto.is_symlink() or not objeto.is_file() or objeto.stat().st_size != validado["bytes"]:
        raise ErroPacotePAM("objeto ausente ou não regular")
    bytes_originais = objeto.read_bytes()
    if hashlib.sha256(bytes_originais).hexdigest() != validado["sha256"]:
        raise ErroPacotePAM("objeto mudou durante a auditoria")
    return meta, bytes_originais, capturado, origem


def preparar_pacote_pam_quarentena(
    *, raiz: str | Path, recibo_sidra: str, plano: dict,
    recibo_pdf: str | None = None, data_publicacao_declarada: str | None = None,
    versao_anterior_sha256: str | None = None,
) -> dict:
    """Monta dossiê informativo, sem nenhum efeito no banco canônico.

    Documento PDF, quando fornecido, só recebe papel de EVIDÊNCIA ANEXADA:
    não se presume que prove o valor específico do JSON SIDRA, nem que
    seu conteúdo é autêntico, nem que permita uso para treino.
    """
    if not isinstance(plano, dict):
        raise ErroPacotePAM("plano municipal obrigatório")
    try:
        esperado = planejar_pam_1612(
            municipio_ibge=plano.get("municipio_ibge"),
            ano=plano.get("ano"),
            codigo_produto_c81=plano.get("categoria_c81"),
            codigo_variavel=plano.get("variavel"))
    except ErroSIDRAPAM as exc:
        raise ErroPacotePAM("plano SIDRA inválido") from exc
    if esperado != plano:
        raise ErroPacotePAM("plano SIDRA divergente do planejador canônico")
    try:
        sem = conferir_semantica_pam_1612(
            variavel=plano["variavel"], categoria_c81=plano["categoria_c81"],
            unidade="Toneladas" if plano["variavel"] == "214" else "Hectares")
    except ErroSemanticaPAM as exc:
        raise ErroPacotePAM("unidade/variável/cultura não reconhecidas") from exc

    meta, dados, coleta, url = _arquivo_recibo(raiz, recibo_sidra)
    if meta.get("tipo") != "SIDRA_JSON" or url != plano["url"]:
        raise ErroPacotePAM("recibo SIDRA não pertence ao município/ano/cultura planejados")
    try:
        normalizado = normalizar_pam_1612(
            dados, plano=plano, coletado_em=coleta.isoformat())
    except (ErroSIDRAPAM, UnicodeError) as exc:
        raise ErroPacotePAM("célula SIDRA inválida ou de outro recorte") from exc
    if len(normalizado["observacoes"]) != 1:
        raise ErroPacotePAM("consulta pontual deve conter uma única célula")
    dado = normalizado["observacoes"][0]
    if dado["unidade_original"] != sem["unidade"]:
        raise ErroPacotePAM("unidade retornada não corresponde à grandeza")
    if normalizado["sha256_original"] != meta["sha256"]:
        raise ErroPacotePAM("normalização não corresponde aos bytes arquivados")

    pdf = None
    if recibo_pdf is not None:
        doc, bruto, capturado_pdf, documento_url = _arquivo_recibo(raiz, recibo_pdf)
        if doc["tipo"] != "PDF_IBGE" or not bruto.startswith(b"%PDF-"):
            raise ErroPacotePAM("documento PDF anexado não é PDF da quarentena")
        if doc["referencia_direitos_declarada"] != meta["referencia_direitos_declarada"]:
            raise ErroPacotePAM("documento e JSON usam declarações de direitos incompatíveis")
        pdf = {
            "url_declarada": documento_url,
            "sha256": doc["sha256"],
            "recibo_sha256": recibo_pdf,
            "captura_declarada_em": capturado_pdf.isoformat(),
            "conteudo_revisado_para_o_alvo": False,
            "autenticidade_ou_data_oficial_comprovadas": False,
        }

    publicacao = None
    if data_publicacao_declarada is not None:
        if not isinstance(data_publicacao_declarada, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", data_publicacao_declarada):
            raise ErroPacotePAM("dia de publicação declarado inválido")
        from datetime import date
        try:
            dia = date.fromisoformat(data_publicacao_declarada)
        except ValueError as exc:
            raise ErroPacotePAM("dia declarado inexistente") from exc
        if dia > coleta.date() or (pdf and dia.isoformat() > pdf["captura_declarada_em"][:10]):
            raise ErroPacotePAM("publicação declarada posterior a uma das capturas")
        publicacao = dia.isoformat()
    if versao_anterior_sha256 is not None:
        if not isinstance(versao_anterior_sha256, str) or not _HASH.fullmatch(versao_anterior_sha256):
            raise ErroPacotePAM("hash de versão anterior inválido")
        # A referência a uma versão antiga NÃO prova posse dos seus bytes
        # nem sua validade. Não permitir marcação automática como disponível.
    blockers = [
        "AUTENTICIDADE_EXTERNA_NAO_VERIFICADA",
        "DATA_PUBLICACAO_OFICIAL_NAO_ATESTADA",
        "LICENCA_E_FINALIDADE_DE_TREINO_NAO_VERIFICADAS",
        "REVISAO_DOCUMENTAL_INDEPENDENTE_PENDENTE",
        "ROTULO_ANUAL_REALIZADO_NAO_CERTIFICADO",
    ]
    if pdf is None:
        blockers.append("DOCUMENTO_OFICIAL_ANEXO_AUSENTE")
    if dado["estado_valor"] != "OBSERVADO_NUMERICO":
        blockers.append("VALOR_SIDRA_MARCADOR_NAO_EXATO")
    if versao_anterior_sha256 is None:
        blockers.append("VERSAO_HISTORICA_ANTERIOR_NAO_FORNECIDA")
    else:
        blockers.append("VERSAO_HISTORICA_CITADA_MAS_NAO_CONFERIDA")
    return {
        "estado": "PACOTE_PAM_QUARENTENA_AUDITORIA_PENDENTE",
        "fonte": "IBGE", "dataset_id": "IBGE_PAM",
        "municipio_ibge": plano["municipio_ibge"], "ano_civil": plano["ano"],
        "produto": sem["produto"], "categoria_c81": plano["categoria_c81"],
        "indicador": sem["indicador"], "unidade": sem["unidade"],
        "celula_sidra": {"estado_valor": dado["estado_valor"],
                        "valor_candidato_nao_certificado": dado["valor"] if dado["estado_valor"] == "OBSERVADO_NUMERICO" else None},
        "captura_json_declarada_em": coleta.isoformat(),
        "publicacao_declarada_nao_verificada": publicacao,
        "url_json": url, "json_sha256": meta["sha256"],
        "recibo_json_sha256": recibo_sidra, "documento_anexo": pdf,
        "versao_anterior_sha256_nao_validada": versao_anterior_sha256,
        "bloqueios": blockers, "bloqueios_count": len(blockers),
        "ledger_canonico_modificado": False,
        "coleta_remota_comprovada": False,
        "dados_reais_homologados": False,
        "treinamento_real_habilitado": False,
        "modelo_promovido": False,
        "aviso": ("Integridade local confirmada. Data, origem, escopo de PDF, "
                  "licenças e verdade estatística permanecem NÃO VERIFICADOS."),
    }
