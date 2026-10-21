import unittest
from datetime import datetime,timezone
from hashlib import sha256

from nivon.conab_store import abrir_series,salvar_edicao
from nivon.series_ambientais import Ambiental,abrir_ambiental,salvar_lote
from nivon.ivo_dossie_agroclimatico import dossie_agroclimatico_asof,ErroDossie

UTC=timezone.utc

def d(y,m,day):return datetime(y,m,day,12,tzinfo=UTC)

def conab_rows():
    return [{
        "origem_sha256":"a"*64,"arquivo":"SojaSerieHist.xls",
        "produto":"SOJA","subdivisao_safra":"TOTAL",
        "coletado_em":"2026-10-18T13:00:00Z","regiao_uf":"MT",
        "safra":"2025/2026","indicador":"PRODUCAO","unidade":"T",
        "valor":5000.,"classificacao":"INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO",
        "rotulo_coluna_original":"2025/2026","rotulo_coluna_inferido":False,
    }]

def clima_rows(n=28):
    sha=sha256(b"fixture-ambiente").hexdigest()
    return [Ambiental(
        dataset_id="INMET_ESTACOES",estacao_id="A123",
        data_local=f"2026-02-{day:02d}",metrica="CHUVA_DIA_MM",
        valor=2.,unidade="MM",natureza="OBSERVADO",
        origem_sha256=sha,referencia="2026-02-28",
        publicado_em=d(2026,3,3).isoformat(),
        coletado_em=d(2026,3,4).isoformat(),
        evidencia="teste-sintetico") for day in range(1,n+1)]

class TestIVODossieAgroclimatico(unittest.TestCase):
    def setUp(self):
        self.a=abrir_series(":memory:")
        self.b=abrir_ambiental()
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)

    def gerar(self,**kw):
        args=dict(conab_db=self.a,ambiental_db=self.b,
                  corte=d(2026,10,21),
                  arquivo_conab="SojaSerieHist.xls",uf="MT",
                  indicador_agricola="PRODUCAO",
                  dataset_ambiental="INMET_ESTACOES",
                  estacao_id="A123",metrica_ambiental="CHUVA_DIA_MM",
                  mes_ambiental="2026-02")
        args.update(kw)
        return dossie_agroclimatico_asof(**args)

    def test_dossie_usa_os_bancos_reais_do_nivon_sem_inventar_relacao(self):
        salvar_edicao(self.a,conab_rows(),publicado_em="2026-10-15")
        salvar_lote(self.b,clima_rows())
        r=self.gerar()
        self.assertEqual(r["fontes_consultadas"],2)
        self.assertEqual(r["fontes_disponiveis"],2)
        self.assertEqual(r["agricultura"]["safras"],1)
        self.assertEqual(r["ambiente"]["valor_mensal"],56.)
        self.assertFalse(r["previsao_intersetorial_homologada"])
        self.assertFalse(r["conexao_causal_demonstrada"])
        self.assertFalse(r["localizacao_estacao_na_uf_verificada"])
        self.assertFalse(r["conversao_safra_mes_realizada"])
        self.assertFalse(r["treinamento_autonomo_habilitado"])
        self.assertFalse(r["publicacao_comercial_autorizada"])

    def test_sem_dados_nao_relata_fontes_disponiveis(self):
        r=self.gerar()
        self.assertEqual(r["fontes_disponiveis"],0)
        self.assertEqual(r["agricultura"]["safras"],0)
        self.assertEqual(r["ambiente"]["dias_ausentes"],28)

    def test_corte_anterior_a_publicacao_nao_vaza_conab(self):
        salvar_edicao(self.a,conab_rows(),publicado_em="2026-10-15")
        salvar_lote(self.b,clima_rows())
        r=self.gerar(corte=d(2026,10,17))
        self.assertEqual(r["agricultura"]["safras"],0)
        self.assertEqual(r["fontes_disponiveis"],1)

    def test_estacao_com_cobertura_incompleta_nao_autoriza_estimativa(self):
        salvar_edicao(self.a,conab_rows(),publicado_em="2026-10-15")
        salvar_lote(self.b,clima_rows(27))
        r=self.gerar()
        self.assertEqual(r["fontes_disponiveis"],1)
        self.assertIsNone(r["ambiente"]["valor_mensal"])

    def test_fuso_obrigatorio(self):
        with self.assertRaises(ErroDossie):
            self.gerar(corte=datetime(2026,10,21))

if __name__=="__main__":
    unittest.main()
