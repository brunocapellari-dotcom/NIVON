"""Normalização conservadora de planilhas XLS oficiais de séries CONAB.

Cada célula válida vira observação identificada por produto, safra, região,
indicador, competência e hash/vintage de origem. Unidades são convertidas de
forma EXPLÍCITA. Não rotular revisão/projeção da CONAB como realizado.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
import re

UF = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
ARQUIVOS = {
    "SojaSerieHist.xls": ("SOJA","TOTAL"),
    "Milho1aSerieHist.xls": ("MILHO","PRIMEIRA"),
    "Milho2aSerieHist.xls": ("MILHO","SEGUNDA"),
    "Milho3aSerieHist.xls": ("MILHO","TERCEIRA"),
    "MilhoTotalSerieHist.xls": ("MILHO","TOTAL"),
}
ABAS = {
    "Área": ("AREA", "mil hectares", "HA", 1000.0),
    "Produtividade": ("PRODUTIVIDADE", "kg/ha", "KG_HA", 1.0),
    "Produção": ("PRODUCAO", "mil toneladas", "T", 1000.0),
}
PADRAO_SAFRA = re.compile(r"^((?:19|20)\d\d)/(\d\d)(?:\s+(?:Previsão|Estimativa|Projeção)(?:\s*\([^)]*\))?)?$", re.IGNORECASE)

class ErroConab(ValueError): pass


def safra_normalizada(valor):
    if not isinstance(valor,str): raise ErroConab("safra não é texto")
    m=PADRAO_SAFRA.fullmatch(valor.strip())
    if not m: raise ErroConab(f"safra inválida: {valor[:30]}")
    ano=int(m.group(1)); seguinte=int(m.group(2))
    if (ano+1)%100 != seguinte: raise ErroConab("safra com anos incompatíveis")
    return f"{ano}/{ano+1}"


def _validar_unidade(sheet,nome):
    esperado=ABAS[nome][1].casefold()
    celulas=" ".join(str(sheet.cell_value(r,0)) for r in range(min(sheet.nrows,6))).casefold()
    # Fonte usa título "Em mil hectares", "Em kg/ha", "Em mil toneladas"
    if esperado not in celulas:
        raise ErroConab(f"{nome}: unidade da aba não corresponde ao contrato")


def normalizar_livro(livro, nome_arquivo: str, *, sha256: str, capturado_em: str):
    if nome_arquivo not in ARQUIVOS: raise ErroConab("arquivo fora do catálogo")
    if not re.fullmatch(r"[a-f0-9]{64}",sha256): raise ErroConab("hash da fonte ausente")
    if not capturado_em: raise ErroConab("data de coleta ausente")
    if set(livro.sheet_names()) != set(ABAS):
        raise ErroConab("abas não correspondem ao contrato")
    produto,safra_tipo=ARQUIVOS[nome_arquivo]
    linhas=[]
    safras_esperadas=None
    for nome, (indicador, _, unidade, multiplicador) in ABAS.items():
        aba=livro.sheet_by_name(nome)
        if aba.nrows < 15 or aba.ncols < 10 or aba.ncols > 130:
            raise ErroConab("dimensões inesperadas da planilha")
        cabecalhos=[r for r in range(min(12,aba.nrows))
                    if str(aba.cell_value(r,0)).strip().upper().startswith("REGIÃO/UF")]
        if len(cabecalhos)!=1: raise ErroConab("linha de cabeçalho geográfico ambígua")
        header=cabecalhos[0]
        _validar_unidade(aba,nome)
        safras=[]
        for col in range(1,aba.ncols):
            raw=aba.cell_value(header,col)
            if raw=="" or raw is None: continue
            try:
                ano_coluna=safra_normalizada(str(raw))
            except ErroConab as exc:
                # CONAB 15/10/2026: célula Produtividade!AI6 tem rótulo
                # corrompido "200.9", enquanto Área!AI6 guarda safra válida.
                # Inferir SOMENTE esse defeito documentado, guardando original.
                if (nome=="Produtividade" and str(raw)=="200.9" and
                    safras_esperadas is not None and col-1 < len(safras_esperadas) and
                    safras_esperadas[col-1]=="2009/2010"):
                    ano_coluna=safras_esperadas[col-1]
                else:
                    raise ErroConab(f"{nome} coluna {col+1}, rotulo={str(raw)[:40]!r}: {exc}") from exc
            safras.append((col,ano_coluna,str(raw)))
        if len(safras)<20 or len({s for _,s,_ in safras})!=len(safras):
            raise ErroConab("safras históricas insuficientes ou repetidas")
        if safras_esperadas is not None and [s for _,s,_ in safras]!=safras_esperadas:
            raise ErroConab("diferença de safras entre as três abas")
        safras_esperadas=[s for _,s,_ in safras]
        regioes=set()
        for row in range(header+1,aba.nrows):
            regiao=str(aba.cell_value(row,0)).strip().upper()
            if regiao=="BRASIL": regiao="BR"
            if regiao not in UF and regiao!="BR": continue
            if regiao in regioes: raise ErroConab("região duplicada dentro da aba")
            regioes.add(regiao)
            for col,safra,rotulo_original in safras:
                raw=aba.cell_value(row,col)
                if raw in ("",None,"-","–","—"): continue
                if type(raw) not in (int,float) or not isfinite(float(raw)) or raw<0:
                    raise ErroConab(f"{nome}: {regiao}, linha {row+1}, coluna {col+1}, safra {safra}, valor={str(raw)[:35]!r} inválido")
                linhas.append({
                    "produto":produto,"subdivisao_safra":safra_tipo,
                    "regiao_uf":regiao,"safra":safra,"indicador":indicador,
                    "valor":round(float(raw)*multiplicador,6),"unidade":unidade,
                    "fonte":"CONAB","arquivo":nome_arquivo,
                    "origem_sha256":sha256,"coletado_em":capturado_em,
                    "classificacao":("PROJETADO_CONAB" if any(p in rotulo_original.casefold() for p in ("previsão","estimativa","projeção")) else "INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO"),
                    "rotulo_coluna_original":rotulo_original,
                    "rotulo_coluna_inferido": (rotulo_original=="200.9"),
                    "celula":{"linha":row+1,"coluna":col+1,"aba":nome},
                })
        if "MT" not in regioes or "BR" not in regioes:
            raise ErroConab("MT ou Brasil ausente na planilha")
    return linhas


def conferir_total_milho(registros, *, tolerancia_relativa=0.002):
    """Confronta Brasil/MT de milho total com três safras, SEM somar de novo."""
    if not 0<=tolerancia_relativa<=0.01: raise ErroConab("tolerância inválida")
    lookup={}
    for d in registros:
        if d["produto"]!="MILHO" or d["indicador"]!="PRODUCAO" or d["regiao_uf"] not in ("BR","MT"):
            continue
        k=(d["regiao_uf"],d["safra"],d["subdivisao_safra"])
        if k in lookup: raise ErroConab("produção duplicada no mesmo recorte")
        lookup[k]=d["valor"]
    saida=[]
    for uf in ("BR","MT"):
        safras={s for (u,s,k) in lookup if u==uf and k=="TOTAL"}
        for safra in sorted(safras):
            k=(uf,safra)
            partes=[lookup.get((uf,safra,p)) for p in ("PRIMEIRA","SEGUNDA","TERCEIRA")]
            total=lookup.get((uf,safra,"TOTAL"))
            if any(p is None for p in partes): # Ausente != zero
                saida.append({"uf":uf,"safra":safra,"status":"NAO_COMPARAVEL_PARCELA_AUSENTE"})
                continue
            soma=sum(partes)
            diferenca=total-soma
            base=max(total,1.0)
            ok=abs(diferenca)<=max(1.0,base*tolerancia_relativa)
            saida.append({"uf":uf,"safra":safra,"status":"CONCILIADO" if ok else "DIVERGENTE",
                          "total_t":total,"soma_t":soma,"diferenca_t":diferenca})
    return saida
