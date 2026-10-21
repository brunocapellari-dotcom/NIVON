"""IVO: conciliação bottom-up de grandezas explicitamente aditivas.

Sem dados externos ou dependências pesadas. A completude territorial das
folhas é declarada pelo caller, não provada pelo grafo. Não soma preços,
produtividades, rendimentos, percentuais ou estoques em datas divergentes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from math import fsum, isfinite
from hashlib import sha256


class ErroHierarquia(ValueError):
    pass


ADITIVAS = frozenset({
    "PRODUCAO_T", "AREA_HA", "EXPORTACAO_T", "IMPORTACAO_T",
    "ABATE_CABECAS", "MOAGEM_T", "MOVIMENTACAO_T", "CONSUMO_T",
    "CAPACIDADE_ESTATICA_T", "ESTOQUE_T",
})


def _id(s):
    if not isinstance(s, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", s) is None:
        raise ErroHierarquia("identificador canônico inválido")
    return s


def _periodo(calendario, periodo):
    if calendario == "MENSAL":
        return isinstance(periodo, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periodo) is not None
    if calendario == "ANO_CIVIL":
        return isinstance(periodo, str) and re.fullmatch(r"\d{4}", periodo) is not None
    if calendario == "SAFRA":
        if not isinstance(periodo, str) or re.fullmatch(r"20\d{2}/20\d{2}", periodo) is None:
            return False
        return int(periodo[5:]) == int(periodo[:4]) + 1
    return False


@dataclass(frozen=True)
class FolhaPrevisao:
    id: str
    valor: float
    indicador: str
    produto: str
    unidade: str
    calendario: str
    periodo: str
    versao_modelo: str
    evidencia_sha256: str

    def validar(self):
        _id(self.id)
        _id(self.produto)
        _id(self.versao_modelo)
        if self.indicador not in ADITIVAS:
            raise ErroHierarquia("métrica não aditiva ou fora da lista permitida")
        # A unidade sozinha não prova aditividade, mas veta mistura inconsistente.
        esperado = {
            "AREA_HA": "ha",
            "ABATE_CABECAS": "cabecas",
        }.get(self.indicador, "t")
        if self.unidade != esperado:
            raise ErroHierarquia("unidade incompatível com indicador")
        if not _periodo(self.calendario, self.periodo):
            raise ErroHierarquia("período/calendário incompatíveis")
        if isinstance(self.valor, bool) or not isinstance(self.valor, (int, float)) or not isfinite(self.valor) or self.valor < 0:
            raise ErroHierarquia("valor de folha não finito ou negativo")
        if not isinstance(self.evidencia_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.evidencia_sha256):
            raise ErroHierarquia("folha sem evidência hash")
        return (self.indicador, self.produto, self.unidade, self.calendario, self.periodo, self.versao_modelo)


def consolidar_bottom_up(*, folhas: list[FolhaPrevisao], grupos: dict[str, tuple[str, ...]],
                          raiz: str) -> dict:
    """Exige árvore exclusiva, folhas completas perante estrutura declarada.

    Isso NÃO garante que todos os municípios/estados reais estejam presentes.
    Não fornece intervalos agregados: esses dependem de covariância conjunta.
    """
    _id(raiz)
    if not isinstance(folhas, list) or not folhas or len(folhas) > 2000:
        raise ErroHierarquia("1-2000 folhas requeridas")
    if not isinstance(grupos, dict) or not grupos or len(grupos) > 2000:
        raise ErroHierarquia("hierarquia de agregação ausente/inválida")
    itens = {}
    assinatura = None
    for f in folhas:
        if not isinstance(f, FolhaPrevisao):
            raise ErroHierarquia("tipo de folha inválido")
        sig = f.validar()
        if assinatura is None:
            assinatura = sig
        elif sig != assinatura:
            raise ErroHierarquia("folhas misturam modelo, período, safra, cultura, unidade ou métrica")
        if f.id in itens:
            raise ErroHierarquia("folha duplicada")
        itens[f.id] = f
    pais = {}
    for pai, filhos in grupos.items():
        _id(pai)
        if not isinstance(filhos, tuple) or not filhos or len(filhos) > 2000:
            raise ErroHierarquia("grupo sem filhos declarados")
        if pai in itens:
            raise ErroHierarquia("nó agregado não pode reaparecer como folha")
        if len(filhos) != len(set(filhos)):
            raise ErroHierarquia("filho duplicado dentro do grupo")
        for filho in filhos:
            _id(filho)
            if filho == pai or filho in pais:
                raise ErroHierarquia("ciclo direto ou nó com múltiplos pais")
            pais[filho] = pai
    nos = set(grupos) | set(itens)
    if set(pais) != nos-{raiz} or raiz not in grupos or raiz in pais:
        raise ErroHierarquia("estrutura com filhos ausentes, órfãos ou raiz incorreta")
    if any(filho not in nos for filho in pais):
        raise ErroHierarquia("grupo referencia unidade sem previsão")
    if len(nos)>3500:
        raise ErroHierarquia("grafo excedeu limite")
    memo = {}
    em_visita = set()
    def somar(no, profundidade=0):
        if profundidade>100:
            raise ErroHierarquia("hierarquia excessivamente profunda")
        if no in em_visita:
            raise ErroHierarquia("ciclo na hierarquia")
        if no in memo:
            return memo[no]
        if no in itens:
            v = float(itens[no].valor)
        else:
            em_visita.add(no)
            v = fsum(somar(f, profundidade+1) for f in grupos[no])
            em_visita.remove(no)
        if not isfinite(v):
            raise ErroHierarquia("soma fora de intervalo finito")
        memo[no] = v
        return v
    total = somar(raiz)
    if set(memo) != nos:
        raise ErroHierarquia("nem todas as folhas foram alcançadas")
    proveniencia = sorted((k,v.evidencia_sha256) for k,v in itens.items())
    digest = sha256(repr((assinatura, raiz, sorted(grupos.items()), proveniencia,
                          sorted((k,float(v.valor)) for k,v in itens.items()))).encode("utf-8")).hexdigest()
    return {
        "estado": "CONSOLIDACAO_CANDIDATA_NAO_HOMOLOGADA",
        "raiz": raiz, "total": total, "valores_por_no": dict(sorted(memo.items())),
        "indicador": assinatura[0], "produto": assinatura[1],
        "unidade": assinatura[2], "calendario": assinatura[3],
        "periodo": assinatura[4], "versao_modelo": assinatura[5],
        "folhas": len(itens), "agregados": len(grupos),
        "hash_proveniencia": digest,
        "completude_universo_geografico_homologada": False,
        "intervalos_agregados_disponiveis": False,
        "modelo_homologado": False,
        "alerta": ("Bottom-up consistente com a árvore declarada; NÃO demonstra "
                   "cobertura de todos os municípios, países ou produtores. "
                   "Nunca somar preços, produtividade, médias, taxas ou "
                   "intervalos individuais como se fossem volumes."),
    }
