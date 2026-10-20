"""IVO: planejador agro interdisciplinar somente leitura sobre contratos NIVON.

Não chama LLM, rede, banco, coletores ou funções de motores. O texto do
usuário é tratado como dado não confiável, jamais concede permissões.
O resultado é um plano com proveniência de catálogo, NÃO uma análise realizada.
"""
from __future__ import annotations

import re
import unicodedata


class ErroPlanejamento(ValueError):
    pass


# Uma rota de negócio NÃO é habilitação de execução do motor.
TERMOS = {
    "SOJA": ("soja", "oleaginosa", "esmagamento de soja"),
    "MILHO": ("milho", "safrinha"),
    "ALGODAO": ("algodao", "pluma", "caroco de algodao"),
    "BOI": ("boi", "boiada", "bovinocultura", "frigorifico", "gado de corte"),
    "BEZERRO": ("bezerro", "reposicao bovina"),
    "ACUCAR": ("acucar", "sacarose"),
    "TRIGO": ("trigo", "moagem de trigo"),
    "SORGO": ("sorgo",),
    "FERTILIZANTES": ("fertilizante", "fertilizantes", "ureia", "potassio", "fosfato", "adubacao", "map", "dap", "kcl"),
    "DIESEL": ("diesel", "biodiesel", "ppi do diesel"),
    "ETANOL_DDG": ("etanol", "ddg", "ddgs", "alcool combustivel"),
    "CANA": ("cana", "cana de acucar", "atr", "moagem de cana"),
    "GERGELIM": ("gergelim",),
    "FRANGO": ("frango", "avicultura", "aves", "frigorifico de aves"),
    "SUINO": ("suino", "suinos", "suinocultura", "porco"),
    "LOGISTICA_INTERMODAL": ("ferrovia", "ferrovias", "hidrovia", "intermodal", "transbordo", "modal"),
    "MARITIMO": ("lineup", "line up", "navio", "navios", "fundeio", "porto", "portos", "ais"),
    "MERCADO_MACRO": ("selic", "juros", "inflacao", "cambio", "dolar", "macroeconomia"),
    "BRIEFING_DIARIO": ("briefing", "boletim diario", "resumo diario"),
    "METEOROLOGIA": ("clima", "meteorologia", "chuva", "estiagem", "seca", "el nino", "la nina", "geada", "temperatura"),
    "HIDROLOGIA": ("nivel do rio", "vazao", "hidrologia", "reservatorio", "cheia", "calado", "navegabilidade"),
    "ARMAZENAGEM": ("armazem", "armazens", "silo", "armazenagem", "capacidade estatica"),
    "COMERCIO_EXTERIOR": ("exportacao", "exportacoes", "importacao", "importacoes", "comex", "ncm", "secex"),
    "PETROLEO_ENERGIA": ("petroleo", "brent", "opep", "refinaria", "energia", "barril"),
    "FRETE_RODOVIARIO": ("frete", "fretes", "caminhao", "caminhoes", "rodoviario", "br 163", "transportadora"),
    "RISCO_GEOPOLITICO": ("geopolitica", "guerra", "sancao", "sancoes", "tarifa comercial", "conflito"),
    "INDUSTRIA_PROCESSAMENTO": ("agroindustria", "processamento", "industria", "fabrica", "capacidade industrial"),
}
# CLIMA_HIDRO é fachada histórica; não duplicar METEOROLOGIA/HIDROLOGIA.
INTENCOES = (
    ("PREVISAO", ("prever", "previsao", "projetar", "projecao", "antecipar", "futuro", "cenario", "cenarios")),
    ("MONITORAMENTO", ("monitorar", "acompanhar", "alerta", "vigiar", "detectar")),
    ("EXPLICACAO", ("por que", "porque", "causa", "impacto", "efeito", "explicar", "relacao")),
    ("RELATORIO", ("relatorio", "briefing", "boletim", "resumo")),
)


def _normalizar(texto: str) -> str:
    if not isinstance(texto, str) or not texto.strip() or len(texto) > 4000:
        raise ErroPlanejamento("pergunta obrigatória com no máximo 4.000 caracteres")
    if any(ord(c) < 32 and c not in "\t\n\r" for c in texto):
        raise ErroPlanejamento("pergunta contém caracteres de controle")
    ascii_ = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower())
        if not unicodedata.combining(c)
    )
    return " " + re.sub(r"[^a-z0-9]+", " ", ascii_).strip() + " "


def _ocorrencias(texto: str, palavras: tuple[str, ...]) -> int:
    return sum((" " + palavra + " ") in texto for palavra in palavras)


def planejar_consulta(pergunta: str, *, catalogo=None, matriz=None, registro=None,
                      max_frentes: int = 6) -> dict:
    """Roteia pergunta para frentes reais cadastradas, sem executar ferramentas.

    As dependências são as do catálogo oficial, mesmo quando não homologadas.
    Não presume acesso autorizado a fontes, nem retorna valores de mercado.
    """
    if type(max_frentes) is not int or not 1 <= max_frentes <= 12:
        raise ErroPlanejamento("limite de frentes inválido")
    texto = _normalizar(pergunta)
    if catalogo is None or matriz is None or registro is None:
        from .catalogo_fontes import carregar_catalogo
        from .cobertura import carregar_matriz
        from .registro_motores import carregar_registro, validar_registro
        catalogo = catalogo if catalogo is not None else carregar_catalogo()
        matriz = matriz if matriz is not None else carregar_matriz(catalogo=catalogo)
        registro = registro if registro is not None else carregar_registro()
        validar_registro(registro, matriz)

    if not isinstance(catalogo, dict) or not isinstance(matriz, dict) or not isinstance(registro, dict):
        raise ErroPlanejamento("manifestos obrigatórios")
    sistemas = {s["id"]: s for s in matriz["systems"]}
    motores = {m["front_id"]: m for m in registro["engines"]}
    conjuntos = {d["id"]: d for d in catalogo["datasets"]}
    fontes = {f["id"]: f for f in catalogo["sources"]}
    if len(sistemas) != len(matriz["systems"]) or len(motores) != len(registro["engines"]):
        raise ErroPlanejamento("frentes ou motores duplicados")
    if not set(sistemas).issubset(motores) or not set(sistemas).issubset(TERMOS | {"CLIMA_HIDRO"}):
        raise ErroPlanejamento("registro de motores inconsistente")
    if any(m.get("operational_enabled") is not False or
           m.get("previsao_homologada") is not False for m in motores.values()):
        raise ErroPlanejamento("manifesto alterou política operacional")
    matches = [(sid, _ocorrencias(texto, palavras))
               for sid, palavras in TERMOS.items() if sid in sistemas]
    ranked = sorted(((sid, n) for sid, n in matches if n > 0), key=lambda x: (-x[1], x[0]))
    intencao = next((i for i, palavras in INTENCOES if _ocorrencias(texto, palavras)), "CONSULTA")
    if not ranked:
        return {
            "status": "PRECISA_DE_ESCOPO", "intencao": intencao,
            "frentes": [], "ferramentas_executadas": 0,
            "resposta_numerica_autorizada": False,
            "mensagem": "Informe uma cultura, cadeia ou domínio para consultar os motores NIVON.",
        }
    frentes = []
    for sid, pontos in ranked[:max_frentes]:
        sistema = sistemas[sid]
        motor = motores[sid]
        deps = []
        for identificador in sistema["data"]:
            d = conjuntos.get(identificador)
            if d is None or d.get("source_id") not in fontes:
                raise ErroPlanejamento("dataset/fonte não consta no catálogo")
            fonte = fontes[d["source_id"]]
            # Explicitamente não promover histórico ou código a fonte operacional.
            deps.append({
                "dataset_id": identificador,
                "fonte_id": d["source_id"],
                "prioridade": d.get("priority"),
                "estagio": d.get("stage"),
                "direitos_fonte": fonte.get("rights"),
                "coleta_operacional": False,
                "redistribuicao_comercial": False,
            })
        frentes.append({
            "id": sid, "relevancia_lexical": pontos,
            "indicadores_planejados": sistema["indicators"],
            "riscos_metodologicos": sistema["risks"],
            "motores_registrados_nao_executados": list(motor["entrypoints"]),
            "dependencias": deps, "modelos_homologados": False,
        })
    return {
        "status": "PLANO_OFFLINE_SEM_DADOS_HOMOLOGADOS",
        "intencao": intencao, "frentes": frentes,
        "frentes_elegiveis_encontradas": len(ranked),
        "frentes_retornadas": len(frentes),
        "ferramentas_executadas": 0,
        "resposta_numerica_autorizada": False,
        "previsao_validada": False,
        "aviso": ("Roteamento lexical, não compreensão semântica. Motores cadastrados "
                  "não demonstram dados reais, direitos ou previsão homologada. "
                  "Exige evidência as-of, qualidade, execução autorizada e auditoria."),
    }
