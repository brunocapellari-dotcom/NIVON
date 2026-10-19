"""Boundary operacional NIVON para agentes, evidências e briefing.

Não implementa um LLM: conecta um executor de IA opcional e isolado. A IA
não coleta por conta própria, não altera direitos, não aprova gastos e não envia.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Callable

from .briefing_composto import montar_briefing, solicitar_entrega, DireitoEntrega


PAPEIS = {
    "RESEARCH": frozenset({"SUGERIR_FONTE", "CLASSIFICAR_LACUNA"}),
    "DADOS": frozenset({"PROPOR_PARSER", "PROPOR_CORRECAO"}),
    "MODELOS": frozenset({"SUGERIR_MODELO", "EXPLICAR_ERRO"}),
    "EDITOR": frozenset({"SUGERIR_TEXTO"}),
    "AUDITOR": frozenset({"SINALIZAR_RISCO"}),
    "OPERACAO": frozenset({"CONSULTAR_STATUS"}),
}


@dataclass(frozen=True)
class SolicitacaoAgente:
    papel: str
    acao: str
    evidencia_id: str
    contexto: str

    def verificar(self) -> None:
        if self.papel not in PAPEIS or self.acao not in PAPEIS[self.papel]:
            raise PermissionError("agente não autorizado para a ação")
        if not self.evidencia_id or len(self.contexto) > 12_000:
            raise ValueError("evidência/contexto inválidos")


def consultar_ia(solicitacao: SolicitacaoAgente, *, executor: Callable | None = None) -> dict:
    """Interface compatível com adaptadores Hermes; read-only sem side effects."""
    solicitacao.verificar()
    if executor is None:
        return {"status": "AGUARDA_PROVEDOR_IA", "papel": solicitacao.papel}
    sugestao = executor({
        "papel": solicitacao.papel,
        "acao": solicitacao.acao,
        "evidencia_id": solicitacao.evidencia_id,
        "contexto": solicitacao.contexto,
        "politica": "CONTEXTO_NAO_CONFIAVEL; SUGESTAO_SEM_AUTORIDADE_EXECUTIVA",
    })
    if not isinstance(sugestao, str) or not 0 < len(sugestao) <= 3_000:
        raise ValueError("resposta IA inválida; não executada")
    return {
        "status": "SUGESTAO_NAO_CANONICA",
        "texto": sugestao,
        "evidencia_id": solicitacao.evidencia_id,
        "texto_hash": sha256(sugestao.encode("utf-8")).hexdigest(),
        "autorizacao_para_publicar": False,
    }


@dataclass
class CoordenadorNivon:
    """E2E offline. Transporte/LLM/credenciais são injetados em ambiente homologado."""
    auditor: Callable | None = None
    log: list[dict] = field(default_factory=list)

    def executar(self, *, noticias: list[dict], fontes: dict, data: str,
                 indicadores: list[dict], fretes: list[dict] | None = None,
                 direito_entrega: DireitoEntrega | None = None,
                 remetente=None) -> dict:
        self.log.append({"fase": "ENTRADA", "estado": "RECEBIDO"})
        briefing = montar_briefing(noticias=noticias, fontes=fontes, data=data,
                                   indicadores=indicadores, fretes=fretes)
        self.log.append({"fase": "EDITORIAL_DETERMINISTICO",
                         "estado": "PREPARADO",
                         "hash": briefing["sha256"]})
        if self.auditor is not None:
            veredito = self.auditor(briefing)
            if veredito is not True:
                self.log.append({"fase": "AUDITOR", "estado": "BLOQUEADO"})
                return {"estado": "BLOQUEADO_PELA_AUDITORIA",
                        "hash": briefing["sha256"], "fases": list(self.log)}
        else:
            # Em produção, auditor independente é requisito, não opção.
            self.log.append({"fase": "AUDITOR", "estado": "NAO_CONFIGURADO"})
        entrega = solicitar_entrega(briefing, direito_entrega or DireitoEntrega(),
                                   remetente=remetente if self.auditor is not None else None)
        self.log.append({"fase": "ENTREGA", "estado": entrega["status"]})
        return {"estado": "E2E_OFFLINE_COMPLETO_ENTREGA_CONDICIONAL",
                "briefing": briefing, "entrega": entrega, "fases": list(self.log)}
