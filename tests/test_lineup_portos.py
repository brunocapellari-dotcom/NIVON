"""Tests use invented vessels and port data only."""
import pytest
from nivon.lineup_portos import FONTES, extrair_lineup_html, verificar_cdp, importar_gpv_csv, inferir_presenca_amaggi

def test_registry():
    assert {"suape", "imbituba", "ponta_madeira", "santarem_cdp", "vila_conde_cdp", "itacoatiara_publico", "itacoatiara_amaggi"} <= set(FONTES)

def test_imbituba_programado_nao_realizado():
    html = "<h3>Programacao</h3><table><tr><th>Navio</th><th>Situacao</th><th>Berco</th><th>Carga</th><th>Toneladas</th></tr><tr><td>SHIP TEST</td><td>Esperado</td><td>1</td><td>Soja</td><td>1000</td></tr></table>"
    rows = extrair_lineup_html(html,"imbituba",coletado_em="2026-10-22T22:00:00Z")
    assert len(rows) == 1
    assert rows[0]["status"] == "ESPERADO_PROGRAMADO"
    assert rows[0]["realizado_confirmado"] is False

def test_cdp_stale_flag():
    entries = [{"data_referencia": "01/01/2022"}]
    assert "PROGRAMACAO_DESATUALIZADA" in verificar_cdp(entries,corte="2026-10-22")["flags"]

def test_gpv_requer_autorizacao():
    with pytest.raises(PermissionError):
        importar_gpv_csv("Navio\nSHIP TEST",acesso_autorizado=False,coletado_em="2026-10-22T22:00:00Z")

def test_ais_sem_inventar_carga():
    polygon=[(0,0),(0,1),(1,1),(1,0)]
    events=[{"imo":"1234567","latitude":0.5,"longitude":0.5,"timestamp":f"2026-10-22T{h:02d}:00:00Z"} for h in (12,13,14)]
    rows = inferir_presenca_amaggi(events,geocerca_terminal=polygon)
    assert len(rows)==1
    assert rows[0]["natureza"]=="INFERIDO_AIS"
    assert rows[0]["produto_informado"] is None
    assert rows[0]["realizado_confirmado"] is False
