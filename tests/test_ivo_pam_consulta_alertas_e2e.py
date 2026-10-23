"""E2E do IVO real sobre PAM SQLite e radar de revisões bitemporais.

Executa aquisição local -> backup restaurável -> mudanças -> console IVO.
Sem rede e sem dados reais nos testes. A data testada é COLETA, não
publicação da PAM no passado.
"""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path

from nivon.ivo_pam_operacao import abrir_operacao_pam,processar_captura_pam
from nivon.ivo_pam_ciclo import executar_ciclo_pam
from nivon.ivo_pam_alertas import alertas_revisoes_pam,ErroAlertasPAM
from nivon.ivo_pam_leitura import abrir_pam_somente_leitura,ErroLeituraPAM
from nivon.ivo_console import main as console
from nivon.sidra_pam import planejar_pam_1612

UTC=timezone.utc


def instante(d):
    return datetime(2026,10,d,12,tzinfo=UTC)


def json_sidra(value="100",*,municipio="5107958",ano=2021,
               var="214",cat="2713",unidade="Toneladas",indent=None):
    raw=[
      {"D1C":"Município (Código)","D2C":"Variável (Código)",
       "D3C":"Ano (Código)",
       "D4C":"Produto das lavouras temporárias (Código)",
       "V":"Valor","MN":"Unidade de Medida"},
      {"D1C":municipio,"D2C":var,"D3C":str(ano),
       "D4C":cat,"V":value,"MN":unidade}
    ]
    return json.dumps(raw,ensure_ascii=False,indent=indent).encode()


def plano(*,municipio="5107958",ano=2021,var="214",cat="2713"):
    return planejar_pam_1612(municipio_ibge=municipio,ano=ano,
        codigo_produto_c81=cat,codigo_variavel=var)


class TestIVOIntegralPAM(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.cofre=self.root/"quarentena"
        self.dbfile=self.root/"historico.sqlite"
        self.db=abrir_operacao_pam(self.dbfile)
        self.addCleanup(self.db.close)

    def gravar(self,valor="100",dia=20,**kw):
        p=plano(**{k:v for k,v in kw.items() if k in ("municipio","ano","var","cat")})
        raw=json_sidra(valor,**{k:v for k,v in kw.items() if k in
                                  ("municipio","ano","var","cat","unidade","indent")})
        return processar_captura_pam(db=self.db,raiz=self.cofre,plano=p,
            payload=raw,coletado_em=instante(dia))

    def radar(self,inicio=19,fim=23):
        return alertas_revisoes_pam(self.db,desde_exclusivo=instante(inicio),
                                   ate_inclusivo=instante(fim))

    def consultar_ivo(self,**kw):
        args=["--pergunta","Como evoluiu a soja no município?",
              "--pam-db",str(self.dbfile),"--municipio","5107958",
              "--produto","2713","--variavel","214",
              "--inicio","2021","--fim","2021"]
        for chave,value in kw.items():
            args.extend(["--"+chave.replace("_","-"),str(value)])
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            code=console(args)
        return code,json.loads(buf.getvalue())

    def test_coleta_valor_alterado_gera_alerta_com_delta_e_sha(self):
        self.gravar("100",20)
        original=self.gravar("150",21)
        radar=self.radar(inicio=20)
        self.assertEqual(radar["alteracoes_relevantes"],1)
        evento=radar["eventos"][0]
        self.assertEqual(evento["tipo"],"VALOR_ALTERADO")
        self.assertEqual(evento["valor_anterior"],100.)
        self.assertEqual(evento["valor_atual"],150.)
        self.assertEqual(evento["variacao_absoluta"],50.)
        self.assertEqual(evento["variacao_pct"],50.)
        self.assertEqual(evento["sha_atual"],original["sha256"])
        self.assertFalse(radar["captura_equivale_a_publicacao"])

    def test_recoleta_igual_nao_gera_novos_alertas(self):
        self.gravar("100",20)
        self.gravar("100",21)
        self.assertEqual(self.radar(inicio=20)["alteracoes_relevantes"],0)
        self.assertEqual(self.radar(inicio=20)["contagens"]["SEM_ALTERACAO"],1)

    def test_bytes_diferentes_mesmo_valor_nao_disparam_alerta(self):
        self.gravar("100",20)
        self.gravar("100",21,indent=2)
        report=self.radar(20)
        self.assertEqual(report["alteracoes_relevantes"],0)
        self.assertEqual(report["contagens"]["NOVOS_BYTES_MESMO_VALOR"],1)

    def test_sigilo_substitui_valor_com_estado_e_nao_delta_falso(self):
        self.gravar("100",20)
        self.gravar("X",21)
        e=self.radar(20)["eventos"][0]
        self.assertEqual(e["tipo"],"ESTADO_ALTERADO")
        self.assertIsNone(e["valor_atual"])
        self.assertIsNone(e["variacao_pct"])

    def test_radar_separa_municipios_e_culturas(self):
        self.gravar("100",20)
        self.gravar("200",21,municipio="5107925")
        self.gravar("150",21,cat="2692")
        self.assertEqual(self.radar(20)["alteracoes_relevantes"],0)
        self.assertEqual(self.radar(20)["contagens"]["PRIMEIRA_CAPTURA"],2)

    def test_radar_nao_usa_alteracao_posterior_ao_corte(self):
        self.gravar("100",20)
        self.gravar("150",21)
        self.assertEqual(self.radar(19,20)["alteracoes_relevantes"],0)
        self.assertEqual(self.radar(20,21)["alteracoes_relevantes"],1)

    def test_console_retorna_valores_reais_do_sqlite_sem_chamar_rede(self):
        self.gravar("100",20)
        self.gravar("150",21)
        code,result=self.consultar_ivo(alertas_desde=instante(20).isoformat())
        self.assertEqual(code,0)
        self.assertEqual(result["serie_pam"]["serie_anual"][0]["valor"],150.)
        self.assertEqual(result["alertas_pam"]["alteracoes_relevantes"],1)
        self.assertTrue(result["dados_recuperados_do_sqlite"])
        self.assertFalse(result["coleta_nova_executada"])
        self.assertFalse(result["modelo_preditivo_executado"])

    def test_console_corte_historico_nao_usa_coleta_futura(self):
        self.gravar("100",20)
        self.gravar("150",21)
        code,result=self.consultar_ivo(corte=instante(20).isoformat(),
                                       alertas_desde=instante(19).isoformat())
        self.assertEqual(code,0)
        self.assertEqual(result["serie_pam"]["serie_anual"][0]["valor"],100.)
        self.assertEqual(result["alertas_pam"]["alteracoes_relevantes"],0)

    def test_leitura_sem_criar_arquivo_ou_tabelas(self):
        nao_existe=self.root/"inexistente.sqlite"
        with self.assertRaises(ErroLeituraPAM):
            abrir_pam_somente_leitura(nao_existe)
        self.assertFalse(nao_existe.exists())
        with abrir_pam_somente_leitura(self.dbfile) as leitura:
            with self.assertRaises(Exception):
                leitura.execute("DELETE FROM pam_vintages")

    def test_console_exige_identidade_agricola_completa(self):
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc=console(["--pergunta","soja","--pam-db",str(self.dbfile)])
        self.assertEqual(rc,2)
        self.assertEqual(json.loads(buf.getvalue())["status"],"BLOQUEADO")

    def test_console_nao_inventa_banco_inexistente(self):
        missing=self.root/"desconhecido.sqlite"
        self.gravar("100",20)
        code,result=self.consultar_ivo(pam_db=missing)
        self.assertEqual(code,2)
        self.assertEqual(result["status"],"BLOQUEADO")
        self.assertFalse(missing.exists())

    def test_radar_falha_sem_timezone_ou_intervalo_invertido(self):
        self.gravar("100",20)
        with self.assertRaises(ErroAlertasPAM):
            alertas_revisoes_pam(self.db,desde_exclusivo=datetime(2026,10,19))
        with self.assertRaises(ErroAlertasPAM):
            self.radar(22,20)

    def test_ciclo_restaurado_emite_alertas_apenas_na_revisao(self):
        entrada=self.root/"entrada"
        entrada.mkdir()
        arquivo=entrada/"soja.json"
        task=[dict(municipio_ibge="5107958",ano=2021,variavel="214",
                   categoria_c81="2713",arquivo="soja.json")]
        arquivo.write_bytes(json_sidra("100"))
        primeiro=executar_ciclo_pam(saida=self.root/"ciclo1",tarefas=task,
                modo="LOCAL",entrada=entrada,iniciar_novo=True)
        self.assertEqual(primeiro["alertas"]["alteracoes_relevantes"],0)
        arquivo.write_bytes(json_sidra("150"))
        segundo=executar_ciclo_pam(saida=self.root/"ciclo2",tarefas=task,
                modo="LOCAL",entrada=entrada,
                arquivo_anterior=self.root/"ciclo1"/"estado_pam.zip")
        self.assertEqual(segundo["alertas"]["alteracoes_relevantes"],1)
        self.assertEqual(segundo["alertas"]["eventos"][0]["variacao_absoluta"],50.)
        self.assertEqual(json.loads((self.root/"ciclo2"/"alertas_pam.json").read_text())
                         ["alteracoes_relevantes"],1)
        terceiro=executar_ciclo_pam(saida=self.root/"ciclo3",tarefas=task,
                modo="LOCAL",entrada=entrada,
                arquivo_anterior=self.root/"ciclo2"/"estado_pam.zip")
        self.assertEqual(terceiro["alertas"]["alteracoes_relevantes"],0)
        self.assertEqual(terceiro["alertas"]["contagens"]["SEM_ALTERACAO"],1)
        self.assertEqual(terceiro["backup"]["capturas"],3)
        self.assertEqual(terceiro["backup"]["vintages"],2)


if __name__=="__main__":
    unittest.main()
