"""Observações conservadoras de cana, gergelim, frango e suíno.

Somente dados locais obtidos com autorização. Sem acesso a rede, NCMs
presumidos, séries inventadas, preços inferidos nem esquemas oficiais falsos.
O parser da API SIDRA/planilha CONAB depende de amostra real homologada.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import re

from .motores import DadoInvalido, validar_fonte

UNIDADES = {
    "BOVINO": {
        "ABATE_CABECAS": "CABECAS", "PESO_CARCACAS_KG": "KG",
        "REBANHO_BOVINO_CABECAS": "CABECAS",
    },
    "CANA": {
        "AREA_HA": "HA", "PRODUCAO_CANA_T": "T",
        "PRODUTIVIDADE_KG_HA": "KG_HA", "MOAGEM_CANA_T": "T",
        "ATR_KG_T": "KG_T", "ACUCAR_T": "T",
        "ETANOL_CANA_ANIDRO_L": "L", "ETANOL_CANA_HIDRATADO_L": "L",
    },
    "GERGELIM": {
        "AREA_HA": "HA", "PRODUCAO_GERGELIM_T": "T",
        "PRODUTIVIDADE_KG_HA": "KG_HA",
        "EXPORTACAO_GERGELIM_T": "T", "IMPORTACAO_GERGELIM_T": "T",
        "EXPORTACAO_FOB_USD": "USD",
    },
    "FRANGO": {
        "ABATE_CABECAS": "CABECAS", "PESO_CARCACAS_KG": "KG",
        "EXPORTACAO_PRODUTO_T": "T", "PLANTEL_GALINACEOS_CABECAS": "CABECAS",
    },
    "SUINO": {
        "ABATE_CABECAS": "CABECAS", "PESO_CARCACAS_KG": "KG",
        "EXPORTACAO_PRODUTO_T": "T", "REBANHO_SUINO_CABECAS": "CABECAS",
    },
}
FORMATOS = {
    "ANO_CIVIL": r"20\d{2}",
    "SAFRA": r"20\d{2}/20\d{2}",
    "TRIMESTRE": r"20\d{2}-T[1-4]",
    "MES": r"20\d{2}-(?:0[1-9]|1[0-2])",
}
CLASSES = frozenset({"OBSERVADO", "INFORMADO", "ESTIMADO", "PROJETADO", "INFERIDO"})
TABELAS_SIDRA = {"BOVINO": "1092", "FRANGO": "1094", "SUINO": "1093"}
UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO BR".split())


def _instante(valor, campo):
    if not isinstance(valor, str) or not ("T" in valor or " " in valor):
        raise DadoInvalido(f"{campo}: informe timestamp completo e fuso")
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DadoInvalido(f"{campo}: timestamp inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise DadoInvalido(f"{campo}: fuso obrigatório")
    return d.astimezone(timezone.utc)


@dataclass(frozen=True)
class ObservacaoCadeia:
    produto: str
    uf: str
    calendario: str
    competencia: str
    indicador: str
    valor: float
    unidade: str
    classificacao: str
    fonte_id: str
    referencia: str
    publicacao: str
    coleta: str
    origem_sha256: str

    def __post_init__(self):
        if self.produto not in UNIDADES or self.uf not in UFS:
            raise DadoInvalido("produto/UF não reconhecido")
        if self.calendario not in FORMATOS or not isinstance(self.competencia, str):
            raise DadoInvalido("calendário ou competência inválido")
        if not re.fullmatch(FORMATOS[self.calendario], self.competencia):
            raise DadoInvalido("período não corresponde ao calendário")
        if self.indicador not in UNIDADES[self.produto] or self.unidade != UNIDADES[self.produto][self.indicador]:
            raise DadoInvalido("indicador/unidade incompatíveis")
        if isinstance(self.valor, bool) or not isinstance(self.valor, (float, int)) or not isfinite(self.valor) or self.valor < 0:
            raise DadoInvalido("valor não numérico, ausente ou negativo")
        if self.classificacao not in CLASSES:
            raise DadoInvalido("classificação inválida")
        if not isinstance(self.fonte_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,70}", self.fonte_id):
            raise DadoInvalido("identificador da fonte inválido")
        if not isinstance(self.referencia, str) or not self.referencia.strip():
            raise DadoInvalido("referência da fonte obrigatória")
        if not isinstance(self.origem_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.origem_sha256):
            raise DadoInvalido("SHA-256 de origem obrigatório")
        if _instante(self.publicacao, "publicacao") > _instante(self.coleta, "coleta"):
            raise DadoInvalido("publicação posterior à coleta")


def normalizar_linhas_offline(
    linhas: Iterable[Mapping[str, object]], *,
    produto: str, fonte_id: str, status_fonte: str,
    operacoes_autorizadas: set[str],
    mapeamento: Mapping[str, str],
    calendario: str, classificacao: str, referencia: str,
    publicacao: str, coleta: str, origem_sha256: str,
    max_linhas: int = 100_000,
) -> list[ObservacaoCadeia]:
    """Requer mapeamento nominal feito sobre layout REAL previamente verificado.

    Não implementa chamada à fonte. Falha fechado em nulidade/duplicata.
    """
    validar_fonte(status=status_fonte, operacao="LEITURA",
                  operacoes_autorizadas=operacoes_autorizadas)
    if "ARMAZENAMENTO" not in operacoes_autorizadas:
        raise PermissionError("ARMAZENAMENTO não autorizado")
    campos = ("uf", "competencia", "indicador", "valor", "unidade")
    if not isinstance(mapeamento, Mapping) or any(
        not isinstance(mapeamento.get(k), str) or not mapeamento[k] for k in campos
    ):
        raise DadoInvalido("mapeamento de colunas incompleto")
    if type(max_linhas) is not int or not 1 <= max_linhas <= 100_000:
        raise DadoInvalido("limite de linhas inválido")
    out, vistos = [], set()
    for linha in linhas:
        if len(out) >= max_linhas:
            raise DadoInvalido("limite de linhas excedido")
        if not isinstance(linha, Mapping) or any(mapeamento[k] not in linha for k in campos):
            raise DadoInvalido("colunas faltantes; nulo não é zero")
        numero = linha[mapeamento["valor"]]
        if type(numero) not in (int, float) or not isfinite(numero):
            raise DadoInvalido("valor não numérico: mapeamento da fonte requer conversão explícita")
        obs = ObservacaoCadeia(
            produto=produto, uf=linha[mapeamento["uf"]],
            calendario=calendario, competencia=linha[mapeamento["competencia"]],
            indicador=linha[mapeamento["indicador"]], valor=float(numero),
            unidade=linha[mapeamento["unidade"]], classificacao=classificacao,
            fonte_id=fonte_id, referencia=referencia, publicacao=publicacao,
            coleta=coleta, origem_sha256=origem_sha256)
        k = (obs.uf, obs.calendario, obs.competencia, obs.indicador)
        if k in vistos:
            raise DadoInvalido("observação duplicada no mesmo vintage")
        vistos.add(k)
        out.append(obs)
    if not out:
        raise DadoInvalido("nenhum registro; não inferir zero")
    return out


def normalizar_abate_sidra_offline(
    linhas: Iterable[Mapping[str, object]], *, produto: str, tabela_sidra: str, **contrato,
) -> list[ObservacaoCadeia]:
    """Contrato específico para resultado já transformado de SIDRA 1093/1094.

    A seleção das variáveis, cobertura e unidade da API real ainda precisam
    de validação em cada extração.
    """
    if TABELAS_SIDRA.get(produto) != tabela_sidra:
        raise DadoInvalido("SIDRA 1092 bovinos, 1093 suinos, 1094 frangos")
    if contrato.get("fonte_id") != "IBGE" or contrato.get("calendario") != "TRIMESTRE":
        raise DadoInvalido("abate IBGE deve manter competência trimestral")
    return normalizar_linhas_offline(linhas, produto=produto, **contrato)


def analisar_cadeia(observacoes: Iterable[ObservacaoCadeia]) -> dict:
    regs = list(observacoes)
    if not regs or any(not isinstance(x, ObservacaoCadeia) for x in regs):
        raise DadoInvalido("sem observações verificadas")
    a = regs[0]
    mesma_edicao = (a.produto, a.uf, a.calendario, a.competencia, a.fonte_id,
                    a.origem_sha256, a.publicacao)
    for item in regs:
        if (item.produto, item.uf, item.calendario, item.competencia,
            item.fonte_id, item.origem_sha256, item.publicacao) != mesma_edicao:
            raise DadoInvalido("mistura de recortes ou vintages")
    dados = {o.indicador:o.valor for o in regs}
    if len(dados) != len(regs):
        raise DadoInvalido("indicadores repetidos")
    derivados = {}
    if a.produto in ("GERGELIM", "CANA"):
        area = dados.get("AREA_HA")
        field = "PRODUCAO_GERGELIM_T" if a.produto == "GERGELIM" else "PRODUCAO_CANA_T"
        if area is not None and field in dados:
            if area == 0:
                raise DadoInvalido("área zero com produção, produtividade indefinida")
            result = dados[field] * 1000 / area
            derivados["produtividade_calculada_kg_ha"] = result
            if "PRODUTIVIDADE_KG_HA" in dados:
                val = dados["PRODUTIVIDADE_KG_HA"]
                derivados["produtividade_conciliada_2pct"] = abs(result-val) <= max(1, val*0.02)
    if a.produto == "CANA" and "PRODUCAO_CANA_T" in dados and "MOAGEM_CANA_T" in dados:
        prod = dados["PRODUCAO_CANA_T"]
        if prod == 0:
            raise DadoInvalido("produção zero não permite razão moagem/producao")
        derivados["moagem_producao_indicativa"] = dados["MOAGEM_CANA_T"] / prod
        derivados["ressalva_moagem"] = "VERIFICAR_GEOGRAFIA_E_CALENDARIO_DAS_FONTES"
    if a.produto in ("BOVINO", "FRANGO", "SUINO") and "ABATE_CABECAS" in dados and "PESO_CARCACAS_KG" in dados:
        n = dados["ABATE_CABECAS"]
        if n == 0:
            raise DadoInvalido("abate zero não permite peso médio")
        derivados["peso_medio_carcaca_kg_cabeca"] = dados["PESO_CARCACAS_KG"] / n
    if a.produto == "GERGELIM" and "EXPORTACAO_GERGELIM_T" in dados and "EXPORTACAO_FOB_USD" in dados:
        vol = dados["EXPORTACAO_GERGELIM_T"]
        if vol == 0:
            raise DadoInvalido("exportação nula não permite preço implícito")
        derivados["valor_fob_medio_usd_t"] = dados["EXPORTACAO_FOB_USD"] / vol
        derivados["preco_fob_nao_preco_fazenda"] = True
    return {
        "produto":a.produto, "uf":a.uf, "calendario":a.calendario,
        "competencia":a.competencia, "indicadores":dados, "derivados":derivados,
        "fonte_id":a.fonte_id, "classificacoes":sorted({r.classificacao for r in regs}),
        "publicacao":a.publicacao, "coleta":a.coleta, "origem_sha256":a.origem_sha256,
        "homologado":False,
        "limitacao":"Cálculo offline sobre entradas declaradas, não prova coleta real nem previsão validada.",
    }
