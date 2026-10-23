"""CONAB: evidencia real de disponibilidade ≠ data de coleta do backfill."""
import sqlite3
import unittest
from nivon.conab_store import abrir_series, salvar_edicao
from nivon.conab_vintage_asof import (
    ErroVintageConab, consultar_historico_asof, homologar_evidencia,
    registrar_evidencia, revogar_evidencia,
)

ARQUIVO = "SojaSerieHist.xls"
EVIDENCIA = "b" * 64
URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras"
PARAMS = dict(arquivo=ARQUIVO, uf="MT", indicador="PRODUCAO", safra="2025/2026")


def registro(sha="a"*64, v=100, coletado="2026-10-18T13:00:00Z"):
    return [{
        "origem_sha256":sha,"arquivo":ARQUIVO,
        "produto":"SOJA","subdivisao_safra":"TOTAL","coletado_em":coletado,
        "regiao_uf":"MT","safra":"2025/2026","indicador":"PRODUCAO",
        "unidade":"T","valor":v,"classificacao":"INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO",
        "rotulo_coluna_original":"2025/26","rotulo_coluna_inferido":False,
    }]


class TestConabVintageAsOf(unittest.TestCase):
    def setUp(self):
        self.db=abrir_series(":memory:")
        self.addCleanup(self.db.close)
        salvar_edicao(self.db,registro(),publicado_em="2026-10-15")

    def _registrar(self, sha="a"*64, data="2026-10-16", evidencia=EVIDENCIA):
        return registrar_evidencia(
            self.db,fonte_sha=sha,arquivo=ARQUIVO,
            disponivel_em=data,evidencia_url=URL,
            evidencia_sha256=evidencia,registrado_em="2026-10-19T13:00:00Z")

    def _aprovar(self, sha="a"*64, evidencia=EVIDENCIA):
        return homologar_evidencia(
            self.db,fonte_sha=sha,arquivo=ARQUIVO,
            evidencia_sha256=evidencia,verificador="Auditoria publicação CONAB v1",
            homologado_em="2026-10-20T12:00:00Z",documento_conferido=True)

    def _consulta(self, instante):
        return consultar_historico_asof(self.db,corte_utc=instante,**PARAMS)

    def test_sem_prova_so_visivel_apos_coleta_real(self):
        self.assertIsNone(self._consulta("2026-10-17T18:00:00Z"))
        visivel=self._consulta("2026-10-19T18:00:00Z")
        self.assertEqual(visivel["valor"],100)
        self.assertEqual(visivel["criterio_cutoff"],"COLETA_OBSERVADA")
        self.assertFalse(visivel["data_coleta_retrodatada"])

    def test_evidencia_pendente_nunca_antecipa_corte(self):
        reg=self._registrar()
        self.assertEqual(reg["estado"],"PENDENTE_AUDITORIA")
        self.assertIsNone(self._consulta("2026-10-17T00:00:00Z"))
        self.assertFalse(self._registrar()["registrada"])
        with self.assertRaises(ErroVintageConab):
            registrar_evidencia(self.db,fonte_sha="a"*64,arquivo=ARQUIVO,
                disponivel_em="2026-10-17",evidencia_url=URL,
                evidencia_sha256=EVIDENCIA,registrado_em="2026-10-19T13:00:00Z")

    def test_documento_aprovado_libera_asof_sem_retrodatacao(self):
        self._registrar()
        with self.assertRaises(ErroVintageConab):
            homologar_evidencia(self.db,fonte_sha="a"*64,arquivo=ARQUIVO,
                evidencia_sha256=EVIDENCIA,verificador="review",
                homologado_em="2026-10-20T00:00:00Z",documento_conferido=False)
        self._aprovar()
        self.assertIsNone(self._consulta("2026-10-15T23:59:59Z"))
        result=self._consulta("2026-10-16T12:00:00Z")
        self.assertEqual(result["valor"],100)
        self.assertEqual(result["criterio_cutoff"],"DOCUMENTO_HOMOLOGADO")
        self.assertEqual(result["primeira_coleta"],"2026-10-18T13:00:00+00:00")
        self.assertEqual(result["disponivel_em_documentada"],"2026-10-16")
        self.assertFalse(result["data_coleta_retrodatada"])

    def test_reprovacao_por_datas_e_dominio_nao_oficial(self):
        for data in ("2026-10-14","2026-10-20"):
            with self.subTest(data=data),self.assertRaises(ErroVintageConab):
                self._registrar(data=data)
        with self.assertRaises(ErroVintageConab):
            registrar_evidencia(self.db,fonte_sha="a"*64,arquivo=ARQUIVO,
                disponivel_em="2026-10-16",evidencia_url="https://www.exemplo.com/",
                evidencia_sha256=EVIDENCIA,registrado_em="2026-10-19T13:00:00Z")
        with self.assertRaises(ErroVintageConab):
            registrar_evidencia(self.db,fonte_sha="a"*64,arquivo=ARQUIVO,
                disponivel_em="2026-10-16",evidencia_url=URL,
                evidencia_sha256=EVIDENCIA,registrado_em="2026-10-17T00:00:00Z")

    def test_revogacao_imediatamente_bloqueia_historico(self):
        self._registrar()
        self._aprovar()
        self.assertIsNotNone(self._consulta("2026-10-17T12:00:00Z"))
        revogar_evidencia(self.db,fonte_sha="a"*64,arquivo=ARQUIVO)
        self.assertIsNone(self._consulta("2026-10-17T12:00:00Z"))
        self.assertEqual(self._consulta("2026-10-19T12:00:00Z")["valor"],100)
        with self.assertRaises(ErroVintageConab):
            self._aprovar()

    def test_duas_publicacoes_diferentes_seleciona_mais_recente(self):
        salvar_edicao(self.db,registro(sha="c"*64, v=120,coletado="2026-10-21T12:00:00Z"),
                     publicado_em="2026-10-20")
        self.assertEqual(self._consulta("2026-10-19T12:00:00Z")["valor"],100)
        self.assertEqual(self._consulta("2026-10-22T00:00:00Z")["valor"],120)

    def test_duas_edicoes_mesma_publicacao_sao_ambiguas(self):
        salvar_edicao(self.db,registro(sha="d"*64,v=130,coletado="2026-10-19T12:00:00Z"),
                     publicado_em="2026-10-15")
        self.assertEqual(self._consulta("2026-10-20T00:00:00Z")["status"],
                         "AMBIGUO_VINTAGE_MESMA_PUBLICACAO")

    def test_evidencia_sha_incorreto_e_publicacao_ausente_bloqueados(self):
        self._registrar()
        with self.assertRaises(ErroVintageConab):
            self._aprovar(evidencia="f"*64)
        salvar_edicao(self.db,registro(sha="e"*64, coletado="2026-10-20T18:00:00Z"))
        with self.assertRaises(ErroVintageConab):
            self._registrar(sha="e"*64)

    def test_asof_exige_timezone_e_nao_corrompe_store(self):
        with self.assertRaises(ErroVintageConab):
            self._consulta("2026-10-17T12:00:00")
        self.assertEqual(self.db.execute("SELECT count(*) FROM conab_observacoes").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM conab_edicoes").fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
