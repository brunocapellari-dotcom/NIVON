"""E2E integrado: PAM -> normalização -> quarentena -> SQLite -> consulta/CLI.

Os testes exercitam o fluxo inteiro com arquivos locais e transporte injetado.
Não afirmam coleta real do IBGE nem validam safras reais.
"""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.sidra_pam import planejar_pam_1612
from nivon.ivo_pam_operacao import (
    abrir_operacao_pam, processar_captura_pam, consultar_pam_operacional,
    executar_lote_pam, main, ErroOperacaoPAM,
)

UTC=timezone.utc


def instante(dia,ano=2026,mes=10):
    return datetime(ano,mes,dia,12,tzinfo=UTC)


def plano(mun="5107958",ano=2021,variavel="214",produto="2713"):
    return planejar_pam_1612(municipio_ibge=mun,ano=ano,
        codigo_produto_c81=produto,codigo_variavel=variavel)


def fixture(mun="5107958",ano=2021,variavel="214",produto="2713",
            valor="100",unidade="Toneladas",indentado=False):
    dados=[
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":mun,"D2C":variavel,"D3C":str(ano),
         "D4C":produto,"V":str(valor),"MN":unidade}
    ]
    return json.dumps(dados,ensure_ascii=False,
                      indent=2 if indentado else None).encode()


class TestIVOOperacaoPAME2E(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.cofre=self.root/"cofre"
        self.entrada=self.root/"entrada"
        self.entrada.mkdir()
        self.dbpath=self.root/"operacional.sqlite"
        self.db=abrir_operacao_pam(self.dbpath)
        self.addCleanup(self.db.close)

    def salvar(self,payload=None,*,p=None,tempo=None,origem="ARQUIVO_LOCAL"):
        return processar_captura_pam(
            db=self.db,raiz=self.cofre,plano=p or plano(),
            payload=fixture() if payload is None else payload,
            coletado_em=tempo or instante(21),origem=origem)

    def consultar(self,**kw):
        q={"municipio_ibge":"5107958","ano":2021,
           "variavel":"214","produto":"2713"}
        q.update(kw)
        return consultar_pam_operacional(self.db,**q)

    def tarefa(self,arquivo="base.json",**kw):
        t={"municipio_ibge":"5107958","ano":2021,"variavel":"214",
           "categoria_c81":"2713","arquivo":arquivo}
        t.update(kw)
        return t

    def test_persistencia_e_consulta_apos_reabertura(self):
        row=self.salvar()
        self.assertEqual(row["alteracao"],"PRIMEIRA_CAPTURA")
        self.assertEqual(self.consultar()["capturas"],1)
        self.assertEqual(self.consultar()["ultima"]["valor"],100.)
        self.assertFalse(row["ledger_canonico_modificado"])
        self.assertFalse(self.consultar()["treinamento_real_habilitado"])
        self.assertEqual(len(list((self.cofre/"objetos_sha256").glob("*.bin"))),1)
        self.db.close()
        self.db=abrir_operacao_pam(self.dbpath)
        self.assertEqual(self.consultar()["capturas"],1)

    def test_repeticao_idempotente_mesma_data_versao(self):
        first=self.salvar()
        again=self.salvar()
        self.assertEqual(first["sha256"],again["sha256"])
        self.assertEqual(again["alteracao"],"SEM_ALTERACAO")
        self.assertEqual(self.consultar()["capturas"],1)
        self.assertEqual(len(list((self.cofre/"recibos").glob("*.json"))),1)

    def test_coletas_de_dias_diferentes_preservadas(self):
        self.salvar(tempo=instante(20))
        segunda=self.salvar(tempo=instante(21))
        self.assertEqual(segunda["alteracao"],"SEM_ALTERACAO")
        self.assertEqual(self.consultar()["capturas"],2)
        self.assertEqual(len(list((self.cofre/"objetos_sha256").glob("*.bin"))),1)
        self.assertEqual(len(list((self.cofre/"recibos").glob("*.json"))),2)

    def test_revisao_numerica_e_asof(self):
        original=self.salvar(fixture(valor="100"),tempo=instante(20))
        novo=self.salvar(fixture(valor="150"),tempo=instante(21))
        self.assertNotEqual(original["sha256"],novo["sha256"])
        self.assertEqual(novo["alteracao"],"VALOR_ALTERADO")
        self.assertEqual(self.consultar()["capturas"],2)
        antigo=self.consultar(corte_coleta=instante(20))
        self.assertEqual(antigo["ultima"]["valor"],100.)
        atual=self.consultar(corte_coleta=instante(21))
        self.assertEqual(atual["ultima"]["valor"],150.)
        self.assertFalse(atual["publicacao_reconstituida"])

    def test_mesmo_numero_bytes_diferentes_nao_e_revisao_valor(self):
        self.salvar(fixture(valor="100"),tempo=instante(20))
        changed=self.salvar(fixture(valor="100",indentado=True),tempo=instante(21))
        self.assertEqual(changed["alteracao"],"NOVOS_BYTES_MESMO_VALOR")
        self.assertEqual(self.consultar()["capturas"],2)

    def test_alteracao_de_estado_nao_transforma_zero_em_observado(self):
        self.salvar(fixture(valor="100"),tempo=instante(20))
        new=self.salvar(fixture(valor="X"),tempo=instante(21))
        self.assertEqual(new["alteracao"],"ESTADO_ALTERADO")
        self.assertIsNone(new["valor_candidato"])
        self.assertEqual(self.consultar()["ultima"]["estado_valor"],"SUPRIMIDO_SIGILO")

    def test_area_e_hectares_nao_mistura_producao(self):
        p=plano(variavel="109")
        self.salvar(fixture(variavel="109",unidade="Hectares",valor="250"),p=p)
        r=consultar_pam_operacional(self.db,municipio_ibge="5107958",
            ano=2021,variavel="109",produto="2713")
        self.assertEqual(r["ultima"]["valor"],250.)
        self.assertEqual(r["ultima"]["unidade"],"Hectares")
        self.assertEqual(self.consultar()["capturas"],0)

    def test_lote_local_multiplos_municipios_e_isolamento_de_erro(self):
        (self.entrada/"a.json").write_bytes(fixture())
        (self.entrada/"b.json").write_bytes(fixture(
            mun="5107925",valor="999"))
        (self.entrada/"ruim.json").write_bytes(b"{JSON invalido")
        tasks=[self.tarefa("a.json"),
               self.tarefa("ruim.json"),
               self.tarefa("b.json",municipio_ibge="5107925")]
        rel=executar_lote_pam(db=self.db,raiz=self.cofre,
            tarefas=tasks,modo="LOCAL",entrada=self.entrada)
        self.assertEqual(rel["total"],3)
        self.assertEqual(rel["aprovados"],2)
        self.assertEqual(rel["falhas"],1)
        self.assertEqual([v["status"] for v in rel["resultados"]],
                         ["OK","ERRO","OK"])
        self.assertEqual(self.consultar()["capturas"],1)
        r=consultar_pam_operacional(self.db,municipio_ibge="5107925",
                                    ano=2021,variavel="214",produto="2713")
        self.assertEqual(r["ultima"]["valor"],999.)

    def test_arquivo_local_path_traversal_recusado_lote_continua(self):
        (self.entrada/"ok.json").write_bytes(fixture())
        rel=executar_lote_pam(db=self.db,raiz=self.cofre,
            tarefas=[self.tarefa("../segredo.json"),
                     self.tarefa("ok.json")],modo="LOCAL",entrada=self.entrada)
        self.assertEqual(rel["falhas"],1)
        self.assertEqual(rel["aprovados"],1)

    def test_lote_http_com_mock_completo_de_transporte(self):
        pedidos=[]
        def transporte(url,limit,timeout):
            pedidos.append((url,limit,timeout))
            return fixture(),"application/json"
        rel=executar_lote_pam(db=self.db,raiz=self.cofre,
            tarefas=[self.tarefa(arquivo=None)],modo="PUBLICO_IBGE",
            transporte=transporte)
        self.assertEqual(rel["aprovados"],1)
        self.assertEqual(len(pedidos),1)
        self.assertEqual(rel["resultados"][0]["resultado"]["origem"],
                         "TRANSPORTE_TESTE")
        self.assertEqual(self.consultar()["capturas"],1)

    def test_lote_url_extra_nao_substitui_plano_canonico(self):
        rel=executar_lote_pam(db=self.db,raiz=self.cofre,
            tarefas=[self.tarefa(arquivo=None,url="https://evil.invalid/captura")],
            modo="PUBLICO_IBGE",
            transporte=lambda u,l,t:(fixture(),"application/json"))
        # URL inserida em campo não contratado é ignorada; HTTPS usa
        # apenas o plano reconstruído, nunca uma URL do input.
        self.assertEqual(rel["aprovados"],1)
        self.assertEqual(self.consultar()["capturas"],1)

    def test_cli_local_em_um_unico_comando(self):
        (self.entrada/"a.json").write_bytes(fixture())
        lista=self.root/"tarefas.json"
        lista.write_text(json.dumps([self.tarefa("a.json")]))
        buffer=io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status=main(["--modo","LOCAL","--tarefas",str(lista),
                "--entrada",str(self.entrada),"--db",str(self.dbpath),
                "--acervo",str(self.cofre)])
        result=json.loads(buffer.getvalue())
        self.assertEqual(status,0)
        self.assertEqual(result["aprovados"],1)
        self.assertEqual(self.consultar()["capturas"],1)

    def test_sem_amostra_nao_cria_captura(self):
        with self.assertRaises(ValueError):
            self.salvar(b"")
        self.assertEqual(self.consultar()["capturas"],0)

    def test_categoria_ou_unidade_incompativel_nao_cria_registro(self):
        with self.assertRaises(ValueError):
            self.salvar(fixture(unidade="Hectares"))
        self.assertEqual(self.consultar()["capturas"],0)

    def test_corte_sem_fuso_recusado(self):
        self.salvar()
        with self.assertRaises(ErroOperacaoPAM):
            self.consultar(corte_coleta=datetime(2026,10,21))

if __name__=="__main__":
    unittest.main()
