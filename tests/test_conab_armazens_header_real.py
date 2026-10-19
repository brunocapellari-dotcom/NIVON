import tempfile
import unittest
from pathlib import Path
from nivon.conab_armazens import (
    LAYOUT_CONAB_SICARM_HEADER_V1, agregar_capacidade_local, ErroArmazens,
)

HEADER = (
    "identificacao_armazem;dsc_especie_armazem;dsc_tipo_armazem;"
    "dsc_tipo_entidade;dsc_tipo_pessoa;nom_municipio;cod_ibge;uf;"
    "qtd_capacidade_estatica(t);qtd_capacidade_expedicao(t);"
    "qtd_capacidade_recepcao(t);latitude;longitude;nome_armazenador;endereco;email\n"
)

class TestLayoutConabSicarmCabecalhoReal(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.f = Path(t.name)/"armazens.txt"

    def salvar(self,rows):
        self.f.write_bytes((HEADER+"".join(rows)).encode("cp1252"))

    def linha(self,uid,municipio,uf,ibge,capacidade):
        return f"{uid};A GRANEL;SILO;SINTETICO;JURIDICA;{municipio};{ibge};{uf};{capacidade};999,00;333,00;-12;-55;NOME_PRIVADO;RUA_PRIVADA;EMAIL_PRIVADO\n"

    def test_layout_e_cadastro_sem_expor_contato(self):
        self.salvar([
            self.linha("SINTETICO-A","Lucas do Rio Verde","MT","5105259","1.200,50"),
            self.linha("SINTETICO-B","Sorriso","MT","5107925","800,00"),
        ])
        ibge=[{"uf":"MT","nome":"Lucas do Rio Verde","codigo_ibge":"5105259"},
              {"uf":"MT","nome":"Sorriso","codigo_ibge":"5107925"}]
        r=agregar_capacidade_local(self.f,LAYOUT_CONAB_SICARM_HEADER_V1,
            coletado_em="2026-10-19T12:00:00-04:00",municipios_ibge=ibge)
        self.assertEqual(r["capacidade_total_t"],2000.5)
        self.assertEqual({x["codigo_ibge"] for x in r["agregados"]},{"5105259","5107925"})
        s=str(r)
        for v in ("NOME_PRIVADO","RUA_PRIVADA","EMAIL_PRIVADO","SINTETICO-A"):
            self.assertNotIn(v,s)

    def test_nao_somar_expedicao_recepcao_ou_ocupacao(self):
        self.salvar([self.linha("SINTETICO-C","Sorriso","MT","5107925","10,00")])
        r=agregar_capacidade_local(self.f,LAYOUT_CONAB_SICARM_HEADER_V1,
                                  coletado_em="2026-10-19T16:00:00Z")
        self.assertEqual(r["capacidade_total_t"],10.0)
        self.assertNotIn("999",str(r))
        self.assertNotIn("333",str(r))

    def test_granularidade_repetida_falha_fechado(self):
        self.salvar([self.linha("REPETIDO","Sorriso","MT","5107925","10,00"),
                     self.linha("REPETIDO","Sorriso","MT","5107925","10,00")])
        with self.assertRaises(ErroArmazens):
            agregar_capacidade_local(self.f,LAYOUT_CONAB_SICARM_HEADER_V1,
                                    coletado_em="2026-10-19T16:00:00Z")
