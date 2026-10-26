"""Evolucao historica do NIVON com Theil-Sen e janelas disjuntas.

Leitura point-in-time sobre observacoes ja versionadas no BigQuery.
Economia homogenea e metadados originais obrigatorios; sem banda comercial
e sem fingerprint de origem, motor NAO produz direcao historica.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .dinamica_tendencias import comparar_forca_tendencia
from .motor_tendencias import ErroTendencia
from .painel_operacional import (CLASSES_PRECO, ErroMotor, _decimal, _tempo,
                                 disponivel_pela_coleta)


CHAVES_IDENTIDADE = {
    "FRETE_ANUNCIADO": ("produto", "origem", "destino", "transportadora",
                       "ponto_embarque", "terminal", "equipamento", "regime",
                       "pedagio", "tipo_preco"),
    "CBOT": ("produto", "contrato", "mercado", "tipo_preco"),
    "PRECO_FISICO": ("produto", "praca", "tipo_preco", "regime"),
}


def _bloqueado(motivo, *, classe, serie_id, dias=0):
    return {
        "status": "DADOS_INSUFICIENTES", "tendencia_atual": "INDETERMINADA",
        "dinamica": "INDETERMINADA", "motivo": motivo,
        "classe": classe, "serie_id": serie_id, "dias_validos": dias,
        "publicavel": False, "probabilidades_calibradas": None,
    }


def avaliar_dinamica_historica(observacoes, *, classe, serie_id, as_of,
                               janela=6, max_defasagem_dias=7):
    corte = _tempo(as_of)
    if classe not in CLASSES_PRECO or not isinstance(serie_id, str) or not serie_id:
        raise ErroMotor("classe ou serie_id invalido para dinamica")
    if type(janela) is not int or not 4 <= janela <= 24:
        raise ErroMotor("janela deve ser 4..24")
    if type(max_defasagem_dias) is not int or not 1 <= max_defasagem_dias <= 30:
        raise ErroMotor("limite de frescor invalido")
    if not isinstance(observacoes, list) or len(observacoes) > 10000:
        raise ErroMotor("observacoes excessivas ou invalidas")
    if not observacoes:
        return _bloqueado("sem_observacoes", classe=classe, serie_id=serie_id)
    referencia = None
    por_dia = {}
    por_coleta = 0
    for obs in observacoes:
        if not isinstance(obs, dict) or not isinstance(obs.get("campos"), dict):
            raise ErroMotor("observacao sem campos")
        campos = obs["campos"]
        if campos.get("serie_id") != serie_id or campos.get("classe") != classe:
            raise ErroMotor("mistura de classe e serie economica")
        identidade = tuple(campos.get(k) for k in CHAVES_IDENTIDADE[classe])
        if any(not isinstance(v, str) or not v.strip() for v in identidade):
            return _bloqueado("identidade_economica_incompleta", classe=classe, serie_id=serie_id)
        unidade = obs.get("unidade")
        fonte = obs.get("dataset_id")
        banda = campos.get("banda_absoluta")
        if not isinstance(unidade, str) or not unidade or not isinstance(fonte, str) or not fonte:
            return _bloqueado("unidade_ou_fonte_ausente", classe=classe, serie_id=serie_id)
        if banda is None:
            return _bloqueado("banda_comercial_ausente", classe=classe, serie_id=serie_id)
        banda_val = _decimal(banda, positivo=True)
        ref = (identidade, fonte, unidade, banda_val)
        if referencia is None:
            referencia = ref
        elif ref != referencia:
            raise ErroMotor("mudanca de condicoes economicas, fonte ou banda")
        if obs.get("natureza") not in {"INFORMADO", "OBSERVADO"}:
            continue
        try:
            dia = date.fromisoformat(obs["data_referencia"])
            coleta = _tempo(obs.get("data_coleta"))
            sem_publicacao = (not obs.get("data_publicacao")
                              and disponivel_pela_coleta(obs, classe))
            pub = coleta if sem_publicacao else _tempo(obs.get("data_publicacao"))
        except (KeyError, ValueError, TypeError) as exc:
            raise ErroMotor("proveniencia temporal invalida") from exc
        if not (dia <= pub.date() and pub <= coleta):
            raise ErroMotor("cronologia da fonte inconsistente")
        if coleta > corte or pub > corte or dia > corte.date():
            continue
        por_coleta += sem_publicacao
        fingerprint = obs.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(
            ch not in "0123456789abcdef" for ch in fingerprint
        ):
            return _bloqueado("fingerprint_original_ausente", classe=classe, serie_id=serie_id)
        valor = _decimal(obs.get("valor"), positivo=True)
        val_float = float(valor)
        if Decimal(str(val_float)) != valor:
            return _bloqueado("precisao_decimal_incompativel", classe=classe, serie_id=serie_id)
        # A revisao mais recente da MESMA identidade de observacao prevalece.
        chave = str(obs.get("identidade") or "")
        if not chave:
            return _bloqueado("identidade_observacao_ausente", classe=classe, serie_id=serie_id)
        por_dia.setdefault(dia, {})
        anterior = por_dia[dia].get(chave)
        if anterior is None or coleta > anterior["coleta_dt"]:
            por_dia[dia][chave] = {
                # Interno ao motor (não exposto): sem publicação declarada,
                # a coleta é apenas o limite de disponibilidade da cronologia.
                "periodo": dia.isoformat(), "publicacao": pub.date().isoformat(),
                "coleta": coleta.date().isoformat(), "valor": val_float,
                "fonte_id": fonte, "edicao_sha256": fingerprint,
                "coleta_dt": coleta,
            }
    if len(por_dia) < 2 * janela:
        return _bloqueado("historico_menor_que_duas_janelas", classe=classe,
                         serie_id=serie_id, dias=len(por_dia))
    ultimo = max(por_dia)
    if (corte.date() - ultimo).days > max_defasagem_dias:
        return _bloqueado("historico_defasado", classe=classe,
                         serie_id=serie_id, dias=len(por_dia))
    serie = []
    for dia in sorted(por_dia):
        registros = list(por_dia[dia].values())
        if classe == "FRETE_ANUNCIADO":
            escolhido = max(registros, key=lambda item: (item["valor"], item["edicao_sha256"]))
        elif len(registros) == 1:
            escolhido = registros[0]
        else:
            # Dois precos diferentes do mesmo contrato/praça/tipo no
            # mesmo dia nao podem ser misturados automaticamente.
            if len({x["valor"] for x in registros}) != 1:
                return _bloqueado("multiplicidade_diaria_ambigua", classe=classe,
                                 serie_id=serie_id, dias=len(por_dia))
            escolhido = min(registros, key=lambda x: x["edicao_sha256"])
        serie.append({k: v for k, v in escolhido.items() if k != "coleta_dt"})
    try:
        dinamica = comparar_forca_tendencia(
            serie, as_of=corte.date().isoformat(), fonte_id=referencia[1],
            unidade=referencia[2], frequencia="SESSOES",
            janela=janela, tolerancia_absoluta=float(referencia[3]),
            tolerancia_relativa=0.0, mudanca_minima_forca_em_limiares=1.0,
        )
    except ErroTendencia as exc:
        return _bloqueado("serie_descontinua_ou_metadados_incompativeis",
                         classe=classe, serie_id=serie_id, dias=len(por_dia)) | {
                         "validacao": str(exc)}
    return {
        **dinamica,
        "classe": classe, "serie_id": serie_id,
        "dias_validos": len(por_dia), "publicavel": False,
        "probabilidades_calibradas": None,
        "natureza": "DESCRITIVA_HISTORICA_NAO_PREVISAO",
        "revisoes_as_of": True, "agrupamento_diario_frete": "MAIOR_DIVULGACAO_MESMAS_CONDICOES",
        "observacoes_disponiveis_pela_coleta": por_coleta,
    }
