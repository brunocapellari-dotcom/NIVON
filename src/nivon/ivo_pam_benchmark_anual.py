"""IVO: benchmark ANUAL PAM/SIDRA com reconstrução bitemporal dos arquivos.

Não usa o laboratório MENSAL, não trata PAM como medição definitiva e não
treina com dados reais. Somente arquivos SINTETICO registrados no ledger NIVON
são admitidos neste experimento; nenhum download ou promoção operacional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import fsum
from statistics import median
from sqlite3 import Connection

from .ivo_pam_publicacoes import EventoPAM, historico_edicoes_pam_asof


class ErroBenchmarkAnual(ValueError):
    pass


_MODOS_VERDADE = frozenset(("PRIMEIRA_PUBLICACAO", "ULTIMA_REVISAO_ATE_CORTE"))


def _utc(v):
    if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroBenchmarkAnual("corte_avaliacao exige datetime com timezone")
    return v.astimezone(timezone.utc)


def _anos(inicio, fim):
    if (type(inicio) is not int or type(fim) is not int
            or not 1974 <= inicio <= fim <= 2100 or fim-inicio > 19):
        raise ErroBenchmarkAnual("intervalo anual inválido; máximo 20 anos")
    return range(inicio, fim+1)


def benchmark_pam_anual_sintetico(
    series: dict[int, tuple[EventoPAM, ...]], *,
    registro_db: Connection, inicio: int, fim: int,
    corte_avaliacao: datetime, variavel: str, produto: str,
    unidade: str = "Toneladas", verdade: str = "PRIMEIRA_PUBLICACAO",
    autoriza_experimento: bool = False,
    minimo_anos_treino: int = 3, max_anos_treino: int = 6,
    atraso_maximo_anos: int = 2,
) -> dict:
    """Recria o estado observado em 1º/jan de cada ano previsto.

    Baseline = último ano com publicação/captura já disponíveis;
    candidato = baseline + horizonte * mediana dos incrementos anuais
    observados em anos consecutivos. Medianas de incrementos protegem
    parcialmente contra extremos; não constituem modelo homologado.

    Cada rótulo de avaliação é consultado SOMENTE no corte declarado,
    separado da data de emissão da previsão retrospectiva.
    """
    if autoriza_experimento is not True:
        raise PermissionError("somente experimento sintético explicitamente autorizado")
    if not isinstance(registro_db, Connection):
        raise ErroBenchmarkAnual("registro SQLite canônico obrigatório")
    years = _anos(inicio, fim)
    corte = _utc(corte_avaliacao)
    if verdade not in _MODOS_VERDADE:
        raise ErroBenchmarkAnual("modo de avaliação inválido")
    if (type(minimo_anos_treino) is not int or type(max_anos_treino) is not int
            or not 3 <= minimo_anos_treino <= max_anos_treino <= 20):
        raise ErroBenchmarkAnual("janela anual de treino inválida")
    if type(atraso_maximo_anos) is not int or not 1 <= atraso_maximo_anos <= 3:
        raise ErroBenchmarkAnual("atraso anual permitido inválido")
    if not isinstance(series, dict) or not 1 <= len(series) <= 100:
        raise ErroBenchmarkAnual("coleção anual de eventos inválida")
    if not isinstance(variavel, str) or not variavel.isdecimal() or not isinstance(produto, str) or not produto.isdecimal():
        raise ErroBenchmarkAnual("códigos oficiais da variável/produto obrigatórios")
    if not isinstance(unidade, str) or not unidade.strip():
        raise ErroBenchmarkAnual("unidade anual não declarada")
    geo = None
    # Validação global impede esconder dados REAL_AUTORIZADO ou trocar geografia
    # apenas em uma versão que seria descartada pelo filtro temporal.
    for ano, eventos in series.items():
        if type(ano) is not int or not 1974 <= ano <= 2100:
            raise ErroBenchmarkAnual("competência anual inválida")
        if not isinstance(eventos, tuple) or not 1 <= len(eventos) <= 40:
            raise ErroBenchmarkAnual("versões anuais ausentes/excessivas")
        for e in eventos:
            if not isinstance(e, EventoPAM):
                raise ErroBenchmarkAnual("evento anual não canônico")
            e.validar()
            p = e.plano
            if (p["ano"] != ano or p["variavel"] != variavel
                    or p["categoria_c81"] != produto):
                raise ErroBenchmarkAnual("ano, variável ou cultura não coincidem")
            if geo is None:
                geo = p["municipio_ibge"]
            elif geo != p["municipio_ibge"]:
                raise ErroBenchmarkAnual("não misturar municípios ou culturas no benchmark")
    if any(ano > corte.year for ano in series):
        # As edições futuras podem existir na fixture, mas não são lidas
        # antes do instante de sua divulgação.
        pass

    cache = {}
    def consultar(ano, instante):
        key = (ano, instante)
        if key not in cache:
            if ano not in series:
                cache[key] = None
            else:
                result = historico_edicoes_pam_asof(
                    list(series[ano]), db=registro_db, corte=instante,
                    variavel=variavel, produto=produto, unidade=unidade)
                # Um dataset real jamais entra no benchmark, mesmo se sua
                # publicação for de uma edição futura ainda não visível.
                if any(item["classe_snapshot"] != "SINTETICO"
                       for item in result["historico"]):
                    raise PermissionError("benchmark anual permite somente snapshots sintéticos")
                cache[key] = result
        return cache[key]

    folds = []
    ignorados = []
    for ano_alvo in years:
        emissao = datetime(ano_alvo,1,1,tzinfo=timezone.utc)
        if emissao > corte:
            ignorados.append({"ano":ano_alvo,"motivo":"emissão futura frente ao corte de avaliação"})
            continue
        # Não buscar ano-alvo nas features: PAM anual retrata o ciclo inteiro.
        conhecidos = []
        for anterior in sorted(ano for ano in series if ano < ano_alvo):
            visto = consultar(anterior,emissao)
            if visto is not None and visto["valor_asof"] is not None:
                conhecidos.append((anterior,float(visto["valor_asof"]),
                                   visto["historico"][-1]["json_sha256"]))
        ultimos = conhecidos[-max_anos_treino:]
        if len(ultimos)<minimo_anos_treino:
            ignorados.append({"ano":ano_alvo,"motivo":"menos de três anos publicados e capturados"})
            continue
        anos = [v[0] for v in ultimos]
        if any(b-a != 1 for a,b in zip(anos,anos[1:])):
            ignorados.append({"ano":ano_alvo,"motivo":"lacuna entre anos de treino; sem interpolação"})
            continue
        ultimo_ano, baseline, _ = ultimos[-1]
        horizonte = ano_alvo-ultimo_ano
        if not 1<=horizonte<=atraso_maximo_anos:
            ignorados.append({"ano":ano_alvo,"motivo":"último ano conhecido muito distante"})
            continue
        slopes = [b[1]-a[1] for a,b in zip(ultimos,ultimos[1:])]
        candidato = max(0.,baseline + horizonte*median(slopes))
        realizado = consultar(ano_alvo,corte)
        if realizado is None or not realizado["historico"]:
            ignorados.append({"ano":ano_alvo,"motivo":"ano-alvo não publicado/coletado no corte"})
            continue
        label = (realizado["historico"][0] if verdade=="PRIMEIRA_PUBLICACAO"
                 else realizado["historico"][-1])
        # Também a avaliação NÃO pode reutilizar rótulo antes da emissão.
        label_data = datetime.fromisoformat(label["json_coletado_em"])
        if label_data <= emissao:
            raise ErroBenchmarkAnual("rótulo estava disponível antes da emissão anual")
        y = float(label["valor"])
        folds.append({
            "ano":ano_alvo, "emissao_retrospectiva":emissao.isoformat(),
            "ultimo_ano_conhecido":ultimo_ano, "horizonte_anos":horizonte,
            "baseline_ultimo_ano":baseline,
            "previsao_tendencia_mediana":candidato,
            "resultado_publicado":y, "primeira_ou_ultima_verdade":verdade,
            "erro_baseline":abs(baseline-y),
            "erro_candidato":abs(candidato-y),
            "labels_treino_anos":anos,
            "labels_treino_shas":[v[2] for v in ultimos],
            "rotulo_sha256":label["json_sha256"],
            "rotulo_edicao_id":label["evento_id"],
            "rotulo_capturado_em":label["json_coletado_em"],
            "rotulo_classe":"ESTATISTICA_PAM_INFORMADA_NAO_CERTIFICADA",
        })
    n = len(folds)
    err_a=fsum(f["erro_candidato"] for f in folds)
    err_b=fsum(f["erro_baseline"] for f in folds)
    total=fsum(f["resultado_publicado"] for f in folds)
    return {
        "estado":"BENCHMARK_PAM_ANUAL_SINTETICO_NAO_HOMOLOGADO",
        "fonte":"IBGE_PAM", "municipio_ibge":geo,"variavel":variavel,
        "categoria_c81":produto,"unidade":unidade,"calendario":"ANO_CIVIL",
        "janela":[inicio,fim],"corte_avaliacao":corte.isoformat(),
        "modo_verdade":verdade,"folds":folds,"folds_validos":n,
        "folds_ignorados":ignorados,
        "mae_baseline":err_b/n if n else None,
        "mae_candidato":err_a/n if n else None,
        "wape_baseline":err_b/total if total>0 else None,
        "wape_candidato":err_a/total if total>0 else None,
        "ganho_mae_relativo":(err_b-err_a)/err_b if err_b>0 else None,
        "dados_reais_autorizados":False,"resultado_final_certificado":False,
        "modelo_homologado":False,"promocao_automatica":False,
        "observacao":("Backtest retrospectivo de estatísticas anuais PAM, "
                     "não de medições finais certificadas; PDFs, licenças e "
                     "datas declaradas requerem verificação externa."),
    }
