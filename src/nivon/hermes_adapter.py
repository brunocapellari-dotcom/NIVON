"""Adaptador NIVON para o contrato hermes.contracts.ProjectAdapter.

Sem dependência em runtime do repositório Hermes: compatibilidade estrutural
com seus métodos async health/status/capabilities/query/execute/search/alerts.

Ações são read-only, autorizadas pelo chamador. Nunca aceita caminho de arquivo,
SQL, URL, nome de módulo, prompt ou acesso a segredos fornecidos pelo agente.
Não importa Hermes em produção nem assume que ele esteja operacional.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import json
from datetime import datetime
import sqlite3

from .indicadores_historicos import (
    compor_pacote_historico, indicador_conab, indicador_porto
)
from .rotina_diaria import preparar_rotina
from .observabilidade_local import monitorar_operacao


class ErroIntegracaoHermes(ValueError):
    pass


_CAPACIDADES = frozenset({
    "safra.progress.read",
    "portos.lineup.read",
    "briefing.preview",
    "fertilizantes.importacao.read",
})
_MAX_NOTICIAS = 30
_MAX_INDICADORES = 100
_MAX_FRETES = 40
_MAX_CULTURAS = 12
_MAX_PORTOS = 20


def _lista(payload: Mapping, key: str, max_items: int, kind: type) -> list:
    value = payload.get(key, [])
    if not isinstance(value, list) or len(value) > max_items or any(
        not isinstance(x, kind) for x in value
    ):
        raise ErroIntegracaoHermes("contrato de entrada inválido: " + key)
    return value


def _instante(payload: Mapping) -> str:
    value = payload.get("gerado_em")
    if not isinstance(value, str) or len(value) > 40:
        raise ErroIntegracaoHermes("hora com fuso obrigatória")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroIntegracaoHermes("hora inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroIntegracaoHermes("hora sem fuso")
    return value


class NivonProjectAdapter:
    """Fronteira de consulta NIVON -> Hermes, A0/A1, sem execução mutável."""

    key = "NIVON"

    def __init__(
        self, *,
        autorizador: Callable[[str], bool],
        fontes: Mapping[str, dict],
        conab: sqlite3.Connection | None = None,
        portos: sqlite3.Connection | None = None,
        mercados: sqlite3.Connection | None = None,
        mdic: sqlite3.Connection | None = None,
        diesel: sqlite3.Connection | None = None,
        licencas_mercado: Mapping[str, dict] | None = None,
        outbox: sqlite3.Connection | None = None,
        portos_esperados: tuple[str, ...] = (),
    ) -> None:
        if not callable(autorizador) or not isinstance(fontes, Mapping):
            raise ErroIntegracaoHermes("requer autorização de identidade e fontes")
        if any(not isinstance(k, str) or not isinstance(v, dict) for k, v in fontes.items()):
            raise ErroIntegracaoHermes("mapa de fontes inválido")
        self._autorizar = autorizador
        self._fontes = deepcopy(dict(fontes))
        self._conab = conab
        self._portos = portos
        self._mercados = mercados
        self._mdic = mdic
        self._diesel = diesel
        if licencas_mercado is not None and not isinstance(licencas_mercado,Mapping):
            raise ErroIntegracaoHermes("licenças de mercado inválidas")
        self._licencas_mercado = deepcopy(dict(licencas_mercado or {}))
        self._outbox = outbox
        if not isinstance(portos_esperados, tuple):
            raise ErroIntegracaoHermes("monitoramento portuário inválido")
        self._portos_esperados = portos_esperados

    def _exigir(self, permissao: str = "NIVON_READ") -> None:
        if self._autorizar(permissao) is not True:
            raise PermissionError("identidade/escopo não autorizados")

    async def health(self) -> Mapping[str, object]:
        self._exigir()
        bancos = {}
        for nome, db in (("conab", self._conab), ("portos", self._portos)):
            if db is None:
                bancos[nome] = "UNCONFIGURED"
                continue
            try:
                row = db.execute("SELECT 1").fetchone()
                bancos[nome] = "QUERY_OK" if row and row[0] == 1 else "ERROR"
            except sqlite3.Error:
                bancos[nome] = "ERROR"
        return {
            "project": self.key,
            "status": "READ_ONLY_ADAPTER",
            "bancos": bancos,
            "production_ready": False,
            "authenticated_execution": False,
        }

    async def status(self) -> Mapping[str, object]:
        self._exigir()
        return {
            "project": self.key, "mode": "OFFLINE_READ_ONLY",
            "autonomy": "A1_MAX",
            "real_time_collectors": "NOT_CONTROLLED_HERE",
            "model_validated_on_real_data": False,
            "whatsapp_delivery_enabled": False,
            "external_actions": False,
        }

    async def capabilities(self) -> set[str]:
        self._exigir()
        return set(_CAPACIDADES)

    async def query(self, capability: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        self._exigir("NIVON_READ")
        if capability not in _CAPACIDADES or not isinstance(payload, Mapping) or len(payload) > 12:
            raise ErroIntegracaoHermes("capacidade ou argumentos desconhecidos")
        try:
            raw = json.dumps(dict(payload), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ErroIntegracaoHermes("argumentos precisam ser JSON estrito") from exc
        if len(raw.encode("utf-8")) > 65_536:
            raise ErroIntegracaoHermes("contexto maior que 64 KiB não autorizado")
        data = _instante(payload)
        if capability == "safra.progress.read":
            if self._conab is None:
                return {"status": "SEM_HISTORICO"}
            keys = ("cultura", "safra", "operacao", "uf", "semana")
            if set(payload) != set(keys) | {"gerado_em"} or any(
                not isinstance(payload[k], str) or len(payload[k]) > 50
                for k in keys
            ):
                raise ErroIntegracaoHermes("seletores de progresso inválidos")
            return indicador_conab(
                self._conab, fontes=self._fontes, gerado_em=data,
                **{k: payload[k] for k in keys},
            )
        if capability == "portos.lineup.read":
            if set(payload) != {"porto", "gerado_em"} or not isinstance(payload["porto"], str):
                raise ErroIntegracaoHermes("seletores de porto inválidos")
            if self._portos is None:
                return {"status": "SEM_HISTORICO"}
            if len(payload["porto"]) > 80:
                raise ErroIntegracaoHermes("porto inválido")
            return indicador_porto(
                self._portos, fontes=self._fontes, gerado_em=data,
                porto=payload["porto"],
            )
        if capability == "fertilizantes.importacao.read":
            campos = {"gerado_em","ncm","uf","ano","mes"}
            if set(payload) != campos:
                raise ErroIntegracaoHermes("seletores de importação MDIC inválidos")
            if self._mdic is None:
                return {"status":"SEM_HISTORICO","publicavel":False}
            from .mdic_fertilizantes_asof import resumo_mdic_fertilizante_asof
            direito=self._fontes.get("MDIC_COMEX_NCM",{})
            habilitado=(direito.get("status_direitos")=="APROVADA"
                        and "LEITURA" in direito.get("operacoes",[]))
            return resumo_mdic_fertilizante_asof(
                self._mdic,ncm=payload["ncm"],uf=payload["uf"],
                ano=payload["ano"],mes=payload["mes"],gerado_em=data,
                leitura_autorizada=habilitado,
            )
        # Preview: aceita apenas documentos/observações previamente adquiridos
        # e autorizados. Devolve texto somente se auditor determinístico aprovar.
        allowed = {"gerado_em", "noticias", "indicadores", "fretes", "culturas", "portos", "incluir_ptax_usd", "diesel_localidades", "cotacoes_licenciadas"}
        if not set(payload) <= allowed:
            raise ErroIntegracaoHermes("campo externo não contratado")
        noticias = _lista(payload, "noticias", _MAX_NOTICIAS, dict)
        indicadores = _lista(payload, "indicadores", _MAX_INDICADORES, dict)
        fretes = _lista(payload, "fretes", _MAX_FRETES, dict)
        culturas = _lista(payload, "culturas", _MAX_CULTURAS, dict)
        portos = _lista(payload, "portos", _MAX_PORTOS, str)
        diesel_localidades = _lista(payload, "diesel_localidades", 40, dict)
        cotacoes_licenciadas = _lista(payload, "cotacoes_licenciadas", 40, dict)
        if any(set(loc)!={"uf","municipio","produto"} for loc in diesel_localidades):
            raise ErroIntegracaoHermes("seletores municipais diesel inválidos")
        if any(len(s) > 80 for s in portos):
            raise ErroIntegracaoHermes("porto muito longo")
        if type(payload.get("incluir_ptax_usd",False)) is not bool:
            raise ErroIntegracaoHermes("incluir_ptax_usd deve ser booleano")
        agregado = compor_pacote_historico(
            db_conab=self._conab, db_portos=self._portos,
            db_mercados=self._mercados,
            incluir_ptax_usd=payload.get("incluir_ptax_usd",False),
            db_diesel=self._diesel, diesel_localidades=diesel_localidades,
            cotacoes_licenciadas=cotacoes_licenciadas,
            licencas_verificadas=self._licencas_mercado,
            fontes=self._fontes, gerado_em=data,
            noticias=noticias, indicadores_externos=indicadores,
            fretes=fretes, culturas=culturas, portos=portos,
        )
        bloqueios = [
            {"origem": x["origem"], "status": x["status"]}
            for x in agregado["resultados"]
            if x["status"] != "INDICADOR_VERIFICADO_TEMPO"
        ]
        if bloqueios:
            return {"status": "BLOQUEADO_HISTORICOS",
                    "detalhes": bloqueios, "envio": False}
        result = preparar_rotina(
            pacote=agregado["pacote"], gerado_em=data,
            auditor=lambda x: len(x["rejeicoes"]) == 0, agendar=False
        )
        if result["status"] != "VALIDADO_DRY_RUN":
            return {"status": result["status"],
                    "faltam": result.get("faltam", []), "envio": False}
        return {
            "status": "PREVIEW_AUDITADO_NAO_PUBLICADO",
            "texto": result["texto"],
            "sha256": result["hash"],
            "envio": False, "custo": 0,
            "modelo_preditivo_homologado": False,
        }

    async def execute(self, capability: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        """Não delegar write/send/purchase a uma IA, nem com prompt convincente."""
        raise PermissionError("NIVON: nenhuma ação mutável exposta ao Hermes")

    async def search(self, query: str, *, limit: int = 10) -> Mapping[str, object]:
        self._exigir()
        if not isinstance(query, str) or not 0 < len(query) <= 150 or not 1 <= limit <= 20:
            raise ErroIntegracaoHermes("busca inválida")
        # Não confundir o índice local de capacidades com pesquisa web/científica.
        itens = [c for c in sorted(_CAPACIDADES) if query.casefold() in c.casefold()]
        return {"status": "INDICE_LOCAL_CAPACIDADES", "items": itens[:limit],
                "external_research_executed": False}

    async def alerts(self, *, since: datetime | None = None) -> Mapping[str, object]:
        self._exigir()
        if since is not None and (not isinstance(since, datetime) or since.tzinfo is None):
            raise ErroIntegracaoHermes("since sem fuso")
        instante = datetime.now().astimezone().isoformat()
        # O clock real de infraestrutura deve ser autenticado/sincronizado pelo host.
        diagnostico = monitorar_operacao(
            gerado_em=instante, conab=self._conab, portos=self._portos,
            outbox=self._outbox, mercados=self._mercados,
            portos_esperados=self._portos_esperados,
        )
        return {
            "status": diagnostico["estado"],
            "alerts": diagnostico["alertas"],
            "coverage": diagnostico["cobertura"],
            "warning": "monitoramento somente local; não prova ausência de incidentes",
        }
