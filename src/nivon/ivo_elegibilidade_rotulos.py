"""IVO: gate explícito de labels de treinamento e vintages auditados.

Diferencia observação publicada de projeção, licença de leitura da de
treinamento e auditoria declarada de homologação operacional independente.
Não coleta, instala, altera modelos nem transforma estimativas em realizados.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite

from .historico import Observacao, visao_na_data


class ErroElegibilidade(ValueError):
    pass


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CLASSES = frozenset(("MEDICAO_OBSERVADA", "BALANCO_CONSOLIDADO_AUDITADO",
                      "INFORMADO", "ESTIMADO", "PROJETADO", "INFERIDO"))
_OPERACOES = frozenset(("ARMAZENAMENTO", "ANALISE", "TREINAMENTO", "DERIVACAO"))


def _utc(value: datetime, nome: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ErroElegibilidade(f"{nome}: instante com fuso obrigatório")
    return value.astimezone(timezone.utc)


def _hash(value: str, nome: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ErroElegibilidade(f"{nome}: SHA-256 obrigatório")
    return value


def _string(value: str, nome: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ErroElegibilidade(f"{nome}: texto inválido")
    return value


def hash_observacao(o: Observacao) -> str:
    """Hash reprodutível da linha exata e de seus quatro eixos temporais."""
    if not isinstance(o, Observacao):
        raise ErroElegibilidade("observação canônica obrigatória")
    payload = {
        "fonte": o.fonte, "variavel": o.variavel, "produto": o.produto,
        "regiao": o.regiao, "unidade": o.unidade, "competencia": o.competencia,
        "calendario": o.calendario, "referencia": o.referencia.isoformat(),
        "publicacao": o.publicacao.isoformat(),
        "coleta": _utc(o.coleta, "coleta").isoformat(),
        "valor": float(o.valor), "natureza": o.natureza, "edicao": o.edicao,
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class AtestacaoResultado:
    observacao: Observacao
    dataset_id: str
    arquivo_sha256: str
    observacao_sha256: str
    classe_origem: str
    modalidade: str  # SINTETICO ou REAL_AUTORIZADO
    politica_resultado: str  # MEDICAO_OBSERVADA ou BALANCO_CONSOLIDADO_AUDITADO
    revisores: tuple[str, str]
    autor_modelo: str
    parecer_sha256: str
    direitos_ref: str
    operacoes_aprovadas: frozenset[str]
    aprovado_em: datetime

    def validar(self, *, corte: datetime) -> None:
        _utc(corte, "corte")
        if not isinstance(self.observacao, Observacao):
            raise ErroElegibilidade("observação ausente")
        for name in ("dataset_id", "autor_modelo", "direitos_ref"):
            _string(getattr(self, name), name)
        _hash(self.arquivo_sha256, "arquivo_sha256")
        _hash(self.observacao_sha256, "observacao_sha256")
        _hash(self.parecer_sha256, "parecer_sha256")
        if self.observacao_sha256 != hash_observacao(self.observacao):
            raise ErroElegibilidade("label mudou após emissão do parecer")
        # O hash da edição é a ligação exata com o arquivo de origem,
        # não só a declaração textual da atestação.
        if self.observacao.edicao != self.arquivo_sha256:
            raise ErroElegibilidade("label sem vínculo à edição de origem")
        if self.modalidade not in ("SINTETICO", "REAL_AUTORIZADO"):
            raise ErroElegibilidade("modalidade inválida")
        if self.classe_origem not in _CLASSES or self.politica_resultado not in _CLASSES:
            raise ErroElegibilidade("classe ou política de resultado inválida")
        if (not isinstance(self.revisores, tuple) or len(self.revisores) != 2
                or any(not isinstance(x, str) or not x.strip() for x in self.revisores)
                or len(set(self.revisores)) != 2
                or self.autor_modelo in self.revisores):
            raise ErroElegibilidade("revisão independente por dois responsáveis obrigatória")
        if (not isinstance(self.operacoes_aprovadas, frozenset)
                or not self.operacoes_aprovadas
                or not self.operacoes_aprovadas.issubset(_OPERACOES)):
            raise ErroElegibilidade("operações de licença inválidas")
        aprovado = _utc(self.aprovado_em, "aprovado_em")
        coletado = _utc(self.observacao.coleta, "coleta")
        if (self.observacao.publicacao > coletado.date()
                or coletado > aprovado or aprovado > _utc(corte, "corte")):
            raise ErroElegibilidade("aprovação, publicação ou coleta fora do corte")


def _catalogo_autoriza(catalogo: dict | None, atestacao: AtestacaoResultado) -> bool:
    if not isinstance(catalogo, dict) or not isinstance(catalogo.get("datasets"), list):
        return False
    matches = [d for d in catalogo["datasets"] if isinstance(d, dict)
               and d.get("id") == atestacao.dataset_id]
    if len(matches) != 1:
        return False
    d = matches[0]
    return (d.get("source_id") == atestacao.observacao.fonte
            and d.get("enabled") is True
            and d.get("collection_authorized") is True
            and d.get("training_authorized") is True)



def _registro_confere(db: sqlite3.Connection | None, a: AtestacaoResultado) -> bool:
    """Verifica metadados já escritos no ledger de snapshots do NIVON.

    Metadata não comprova origem externa; uma prova jurídica autenticada e
    checagem de hashes dos bytes reais seguem gates externos obrigatórios.
    """
    if not isinstance(db, sqlite3.Connection):
        return False
    try:
        rows = db.execute(
            """SELECT s.fonte_id,s.sha256,s.publicacao,s.tipo,
                      s.evidencia_direitos,c.coletado_utc
               FROM nivon_snapshots s JOIN nivon_coletas c ON c.snapshot_id=s.id
               WHERE s.dataset_id=? AND s.sha256=?""",
            (a.dataset_id,a.arquivo_sha256)).fetchall()
    except sqlite3.Error:
        return False
    o=a.observacao
    for row in rows:
        fonte,sha,publicacao,tipo,direito,coleta=tuple(row)
        if (fonte,sha,publicacao,tipo,direito)!=(
                o.fonte,a.arquivo_sha256,o.publicacao.isoformat(),
                "REAL_AUTORIZADO",a.direitos_ref):
            continue
        try:
            instante=datetime.fromisoformat(coleta.replace("Z","+00:00"))
        except (AttributeError,ValueError,TypeError):
            continue
        if instante.tzinfo is not None and instante.astimezone(timezone.utc)==_utc(o.coleta,"coleta"):
            return True
    return False


def avaliar_elegibilidade(
    atestacoes: list[AtestacaoResultado], *, corte: datetime,
    catalogo: dict | None = None, permitir_sintetico: bool = False,
    registro_db: sqlite3.Connection | None = None,
    minimo_periodos: int = 3,
) -> dict:
    """Analisa todo o pacote ou bloqueia tudo; não devolve linhas de treino.

    Sinalizar permissões NÃO atesta juridicamente os contratos. No modo
    sintético há um status diferente, impossível confundir com real.
    """
    corte = _utc(corte, "corte")
    if not isinstance(atestacoes, list) or not 1 <= len(atestacoes) <= 5000:
        raise ErroElegibilidade("pacote de labels vazio/excessivo")
    if type(permitir_sintetico) is not bool:
        raise ErroElegibilidade("permissão sintética inválida")
    if type(minimo_periodos) is not int or not 1 <= minimo_periodos <= 1000:
        raise ErroElegibilidade("quantidade mínima inválida")
    bloqueios = []
    chaves = set()
    escopo = None
    direitos_referencias = set()
    modalidades = set()
    for a in atestacoes:
        if not isinstance(a, AtestacaoResultado):
            raise ErroElegibilidade("atestação inválida")
        a.validar(corte=corte)
        o = a.observacao
        scope = (o.fonte, o.variavel, o.produto, o.regiao, o.unidade, o.calendario)
        if escopo is None:
            escopo = scope
        elif scope != escopo:
            raise ErroElegibilidade("não misturar culturas, regiões, séries, unidades ou calendários")
        versao = (o.chave, a.arquivo_sha256, a.observacao_sha256)
        if versao in chaves:
            raise ErroElegibilidade("label/edição duplicado")
        chaves.add(versao)
        direitos_referencias.add(a.direitos_ref)
        modalidades.add(a.modalidade)
        if o.natureza != "OBSERVADO" or a.classe_origem not in (
                "MEDICAO_OBSERVADA", "BALANCO_CONSOLIDADO_AUDITADO"):
            bloqueios.append("NATUREZA_OU_CLASSE_NAO_OBSERVADA")
        if a.politica_resultado != a.classe_origem:
            bloqueios.append("POLITICA_DE_VERDADE_DIVERGENTE")
        if not {"ARMAZENAMENTO", "ANALISE", "TREINAMENTO"}.issubset(a.operacoes_aprovadas):
            bloqueios.append("DIREITOS_DE_TREINAMENTO_NAO_COMPROVADOS")
        if a.modalidade == "SINTETICO":
            if not permitir_sintetico or not a.dataset_id.startswith("TESTE_"):
                bloqueios.append("FIXTURE_SINTETICA_NAO_AUTORIZADA")
        else:
            if not _catalogo_autoriza(catalogo, a):
                bloqueios.append("CATALOGO_REAL_SEM_AUTORIZACAO_DE_TREINO")
            if not _registro_confere(registro_db, a):
                bloqueios.append("SNAPSHOT_REAL_SEM_PROVENIENCIA_CONFERIDA")
    if len(modalidades) != 1:
        bloqueios.append("REAL_E_SINTETICO_MISTURADOS")
    revisoes = visao_na_data(
        [a.observacao for a in atestacoes],
        data_corte_publicacao=corte.date(), instante_corte_coleta=corte)
    if len(revisoes) < minimo_periodos:
        bloqueios.append("PERIODOS_INSUFICIENTES")
    if len({o.competencia for o in revisoes}) != len(revisoes):
        raise ErroElegibilidade("snapshot contém competências duplicadas")
    if bloqueios:
        estado = "BLOQUEADO"
    else:
        estado = ("ELEGIVEL_EXPERIMENTO_SINTETICO" if modalidades == {"SINTETICO"}
                  else "CANDIDATO_REAL_COM_APROVACOES_DECLARADAS")
    digest = sha256(repr(sorted(
        (a.observacao_sha256, a.parecer_sha256,
         _utc(a.aprovado_em, "aprovado_em").isoformat()) for a in atestacoes
    )).encode()).hexdigest()
    return {
        "estado": estado, "bloqueios": sorted(set(bloqueios)),
        "fonte": escopo[0], "indicador": escopo[1], "produto": escopo[2],
        "regiao": escopo[3], "unidade": escopo[4], "calendario": escopo[5],
        "edicoes_recebidas": len(atestacoes), "competencias_asof": len(revisoes),
        "hash_pacote": digest, "referencias_direitos": sorted(direitos_referencias),
        "homologacao_externa_verificada": False,
        "treinamento_executado": False,
        "modelo_promovido": False,
        "nota": ("Atestações e direitos são declarações verificadas contra o "
                 "contrato, não verificação jurídica nem homologação de origem."),
    }


def serie_elegivel_experimental(atestacoes: list[AtestacaoResultado], *,
    corte: datetime, permitir_sintetico: bool = False,
    catalogo: dict | None = None, minimo_periodos: int = 3,
    registro_db: sqlite3.Connection | None = None,
) -> tuple[Observacao, ...]:
    """Preserva todas as vintages sintéticas elegíveis, sem treino real.

    A função consumidora deve aplicar visao_na_data em CADA emissão
    histórica: um snapshot único atual destruiria a trilha de revisões.
    """
    resultado = avaliar_elegibilidade(
        atestacoes, corte=corte, permitir_sintetico=permitir_sintetico,
        catalogo=catalogo, registro_db=registro_db,
        minimo_periodos=minimo_periodos)
    if resultado["estado"] != "ELEGIVEL_EXPERIMENTO_SINTETICO":
        raise PermissionError("labels não habilitados para laboratório sintético")
    # NÃO colapsar as revisões num snapshot "atual". Treinamento
    # walk-forward precisa das versões antigas para reconstruir o que
    # realmente era conhecido em cada emissão histórica.
    return tuple(sorted(
        (a.observacao for a in atestacoes),
        key=lambda o: (o.competencia, o.publicacao,
                       _utc(o.coleta, "coleta"), o.edicao),
    ))
