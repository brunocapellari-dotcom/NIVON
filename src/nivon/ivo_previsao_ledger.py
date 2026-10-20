"""IVO: registro imutável de previsões e resultados com datas as-of.

Implementação SQLite offline e sem dependências externas. Faz auditoria de
previsões LIVE versus BACKTEST; não treina, promove, coleta nem publica modelos.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
from pathlib import Path


class ErroLedger(ValueError):
    pass


def _texto(valor, nome):
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 160:
        raise ErroLedger(f"{nome}: identificação obrigatória (máximo 160 caracteres)")
    return valor


def _instante(valor, nome):
    if not isinstance(valor, datetime) or valor.tzinfo is None or valor.utcoffset() is None:
        raise ErroLedger(f"{nome}: datetime com fuso horário obrigatório")
    return valor.astimezone(timezone.utc)


def _valor(valor, nome):
    if isinstance(valor, bool) or not isinstance(valor, (float, int)) or not isfinite(valor) or valor < 0:
        raise ErroLedger(f"{nome}: número finito não negativo obrigatório")
    return float(valor)


def _periodo(valor):
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", valor):
        raise ErroLedger("período: formato AAAA-MM obrigatório")
    return datetime(int(valor[:4]), int(valor[-2:]), 1, tzinfo=timezone.utc)


def _mes(agora):
    return agora.year * 12 + agora.month


def _hash(valor):
    if not isinstance(valor, str) or not re.fullmatch(r"[a-f0-9]{64}", valor):
        raise ErroLedger("hash SHA-256 hexadecimal obrigatório")
    return valor


@dataclass(frozen=True)
class PrevisaoRegistrada:
    id: str
    modelo_id: str
    versao_modelo: str
    indicador: str
    geografia: str
    unidade: str
    periodo: str
    fonte_verdade: str
    emitida_em: datetime
    disponivel_ate: datetime
    registrada_em: datetime
    estimativa: float
    baseline: float
    evidencia_sha256: str
    modo: str = "BACKTEST"
    limite_inferior: float | None = None
    limite_superior: float | None = None

    def validar(self):
        for nome in ("id", "modelo_id", "versao_modelo", "indicador", "geografia",
                     "unidade", "fonte_verdade"):
            _texto(getattr(self, nome), nome)
        _hash(self.evidencia_sha256)
        inicio = _periodo(self.periodo)
        emitida = _instante(self.emitida_em, "emitida_em")
        corte = _instante(self.disponivel_ate, "disponivel_ate")
        registro = _instante(self.registrada_em, "registrada_em")
        if not corte <= emitida <= registro:
            raise ErroLedger("data disponível deve anteceder emissão e registro")
        horizonte = _mes(inicio) - _mes(emitida)
        if not 1 <= horizonte <= 24 or emitida >= inicio:
            raise ErroLedger("alvo mensal deve estar 1–24 meses após a emissão")
        if self.modo not in ("LIVE", "BACKTEST"):
            raise ErroLedger("modo de avaliação inválido")
        if self.modo == "LIVE" and registro >= inicio:
            raise ErroLedger("previsão LIVE deve estar registrada antes do mês-alvo")
        _valor(self.estimativa, "estimativa")
        _valor(self.baseline, "baseline")
        if (self.limite_inferior is None) != (self.limite_superior is None):
            raise ErroLedger("intervalo incompleto")
        if self.limite_inferior is not None:
            li = _valor(self.limite_inferior, "limite_inferior")
            ls = _valor(self.limite_superior, "limite_superior")
            if not li <= float(self.estimativa) <= ls:
                raise ErroLedger("intervalo não contém estimativa pontual")
        return horizonte


@dataclass(frozen=True)
class ObservacaoPublicada:
    id: str
    fonte_id: str
    indicador: str
    geografia: str
    unidade: str
    periodo: str
    publicada_em: datetime
    registrada_em: datetime
    valor: float
    evidencia_sha256: str

    def validar(self):
        for nome in ("id", "fonte_id", "indicador", "geografia", "unidade"):
            _texto(getattr(self, nome), nome)
        _hash(self.evidencia_sha256)
        inicio = _periodo(self.periodo)
        publicada = _instante(self.publicada_em, "publicada_em")
        registrada = _instante(self.registrada_em, "registrada_em")
        proximo_mes = (inicio.year + int(inicio.month == 12), inicio.month % 12 + 1)
        fechamento = datetime(proximo_mes[0], proximo_mes[1], 1, tzinfo=timezone.utc)
        if publicada < fechamento:
            raise ErroLedger("observação mensal final ainda não pode estar publicada")
        if registrada < publicada:
            raise ErroLedger("registro da observação anterior à publicação")
        _valor(self.valor, "valor")


def _serializar(obj):
    payload = asdict(obj)
    for k, v in payload.items():
        if isinstance(v, datetime):
            payload[k] = _instante(v, k).isoformat()
    json_ = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return json_, sha256(json_.encode("utf-8")).hexdigest()


def _recuperar(record):
    dado = json.loads(record)
    for k, v in dado.items():
        if k.endswith("_em") or k == "disponivel_ate":
            dado[k] = datetime.fromisoformat(v)
    return dado


class LedgerPrevisoes:
    """SQLite sem execuções arbitrárias; registros append-only com conflito negado."""

    def __init__(self, caminho=":memory:"):
        if not isinstance(caminho, (str, Path)):
            raise ErroLedger("caminho inválido")
        if isinstance(caminho, Path) and caminho.is_symlink():
            raise ErroLedger("caminho simbólico não permitido")
        self.conexao = sqlite3.connect(str(caminho))
        self.conexao.execute("PRAGMA foreign_keys = ON")
        with self.conexao:
            self.conexao.execute(
                "CREATE TABLE IF NOT EXISTS ivo_previsoes (id TEXT PRIMARY KEY, payload TEXT NOT NULL, checksum TEXT NOT NULL)")
            self.conexao.execute(
                "CREATE TABLE IF NOT EXISTS ivo_observacoes (id TEXT PRIMARY KEY, payload TEXT NOT NULL, checksum TEXT NOT NULL)")

    def close(self):
        self.conexao.close()

    def _anexar(self, tabela, identificador, obj):
        # Identificador SQL é literal interno, e todos os valores são parametrizados.
        payload, digest = _serializar(obj)
        with self.conexao:
            atual = self.conexao.execute(
                f"SELECT checksum FROM {tabela} WHERE id = ?", (identificador,)
            ).fetchone()
            if atual:
                if atual[0] != digest:
                    raise ErroLedger("id já registrado com conteúdo diferente: correção exige nova versão/id")
                return "IDEMPOTENTE"
            self.conexao.execute(
                f"INSERT INTO {tabela}(id,payload,checksum) VALUES(?,?,?)",
                (identificador, payload, digest))
        return "REGISTRADO"

    def registrar_previsao(self, item: PrevisaoRegistrada):
        if not isinstance(item, PrevisaoRegistrada):
            raise ErroLedger("previsão inválida")
        item.validar()
        if item.modo == "LIVE":
            instante_real = datetime.now(timezone.utc)
            if _periodo(item.periodo) <= instante_real:
                raise ErroLedger("previsão LIVE inserida depois de iniciado mês-alvo")
            if abs(_instante(item.registrada_em, "registrada_em") - instante_real) > timedelta(minutes=15):
                raise ErroLedger("previsão LIVE exige registro próximo do relógio real de ingestão")
        return self._anexar("ivo_previsoes", item.id, item)

    def registrar_observacao(self, item: ObservacaoPublicada):
        if not isinstance(item, ObservacaoPublicada):
            raise ErroLedger("observação inválida")
        item.validar()
        return self._anexar("ivo_observacoes", item.id, item)

    def avaliar(self, *, corte: datetime, modelo_id: str | None = None,
                modo: str = "BACKTEST", verdade: str = "PRIMEIRA_PUBLICACAO"):
        corte = _instante(corte, "corte")
        if modelo_id is not None:
            _texto(modelo_id, "modelo_id")
        if modo not in ("BACKTEST", "LIVE"):
            raise ErroLedger("modo inválido")
        if verdade not in ("PRIMEIRA_PUBLICACAO", "ULTIMA_ATE_CORTE"):
            raise ErroLedger("política de vintage inválida")
        previsoes = [_recuperar(row[0]) for row in self.conexao.execute(
            "SELECT payload FROM ivo_previsoes ORDER BY id")]
        observacoes = [_recuperar(row[0]) for row in self.conexao.execute(
            "SELECT payload FROM ivo_observacoes ORDER BY id")]
        avaliados = []
        pendentes = 0
        for p in previsoes:
            if p["modo"] != modo or (modelo_id is not None and p["modelo_id"] != modelo_id):
                continue
            if p["registrada_em"] > corte:
                continue
            opcoes = [o for o in observacoes if
                      o["fonte_id"] == p["fonte_verdade"]
                      and (o["indicador"], o["geografia"], o["unidade"], o["periodo"])
                      == (p["indicador"], p["geografia"], p["unidade"], p["periodo"])
                      and o["publicada_em"] <= corte and o["registrada_em"] <= corte]
            if not opcoes:
                pendentes += 1
                continue
            o = sorted(opcoes, key=lambda x: (x["publicada_em"], x["registrada_em"], x["id"]))[
                0 if verdade == "PRIMEIRA_PUBLICACAO" else -1]
            real, yhat, base = float(o["valor"]), float(p["estimativa"]), float(p["baseline"])
            li, ls = p["limite_inferior"], p["limite_superior"]
            avaliados.append({
                "previsao_id": p["id"], "modelo_id": p["modelo_id"], "versao_modelo": p["versao_modelo"],
                "indicador": p["indicador"], "geografia": p["geografia"],
                "unidade": p["unidade"], "periodo": p["periodo"],
                "horizonte_meses": _mes(_periodo(p["periodo"])) - _mes(p["emitida_em"]),
                "observado": real, "previsto": yhat, "baseline": base,
                "erro_absoluto": abs(real - yhat), "erro_baseline": abs(real - base),
                "erro_assinado": yhat - real,
                "dentro_intervalo": (li <= real <= ls) if li is not None else None,
                "vintage_publicada_em": o["publicada_em"].isoformat(),
                "observacao_id": o["id"],
            })
        # Médias de preços, chuva, volumes, horizontes ou versões distintas
        # não são comparáveis; manter linhas acessíveis para análise por grupo.
        grupos = {
            (x["modelo_id"], x["versao_modelo"], x["indicador"], x["geografia"],
             x["unidade"], x["horizonte_meses"]) for x in avaliados
        }
        comparavel = len(grupos) <= 1
        n = len(avaliados)
        erro = sum(x["erro_absoluto"] for x in avaliados)
        erro_baseline = sum(x["erro_baseline"] for x in avaliados)
        denominador = sum(abs(x["observado"]) for x in avaliados)
        cobertos = [x["dentro_intervalo"] for x in avaliados if x["dentro_intervalo"] is not None]
        return {
            "status": ("AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA" if comparavel
                       else "BLOQUEADO_AGREGACAO_ESCOPOS_DIFERENTES"),
            "agregacao_comparavel": comparavel,
            "modo": modo, "verdade": verdade, "corte": corte.isoformat(),
            "modelo_id": modelo_id, "avaliadas": n, "sem_observacao": pendentes,
            "mae": erro/n if n and comparavel else None,
            "mae_baseline": erro_baseline/n if n and comparavel else None,
            "wape": erro/denominador if denominador and comparavel else None,
            "vies_medio": sum(x["erro_assinado"] for x in avaliados)/n if n and comparavel else None,
            "ganho_relativo_baseline": ((erro_baseline - erro)/erro_baseline
                                       if erro_baseline and comparavel else None),
            "cobertura_intervalo": sum(cobertos)/len(cobertos) if cobertos and comparavel else None,
            "avaliacoes": avaliados,
            "promocao_automatica": False,
            "limitacao": ("Métricas descritivas não substituem revisão de fonte, independência "
                         "do backtest, correlação temporal, calibração nem gate de homologação."),
        }
