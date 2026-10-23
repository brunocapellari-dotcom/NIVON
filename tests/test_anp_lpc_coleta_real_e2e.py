"""E2E do coletor ANP: HTML oficial sintético -> XLSX -> RAW -> SQLite -> tendência.

Sem rede e sem preço real; CI exige openpyxl. As únicas "autoridades"
que aparecem aqui são etiquetas de fixture.
"""
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from hashlib import sha256
from pathlib import Path

from nivon.anp_lpc_coletor_real import (
    ErroColetaANP, coletar_lpc, obter_documento,
)
from nivon.anp_lpc_staging_real import (
    iniciar_staging, tendencia_diesel_preliminar, painel_qualidade_lpc,
)
from nivon.cli_coletar_anp_lpc import main
from nivon.anp_diesel_pressao_preview import impacto_diesel_anp_preliminar
from decimal import Decimal
from test_anp_lpc_integracao import fixture, Workbook


class Resposta:
    def __init__(self,url,bytes_,mime,status=200,final_url=None):
        self.url=url
        self.data=bytes_
        self.status=status
        self.headers={"Content-Type":mime}
        self._final=final_url or url

    def __enter__(self):
        return self

    def __exit__(self,*args):
        return False

    def read(self,n=-1):
        return self.data[:n]

    def geturl(self):
        return self._final


class AberturaFake:
    def __init__(self,arquivos):
        self.arquivos=arquivos
        self.chamadas=[]

    def open(self,request,timeout=25):
        self.chamadas.append(request.full_url)
        return self.arquivos[request.full_url]


def lote(*, semanas=(date(2026,9,27),date(2026,10,4),
                     date(2026,10,11)), precos=("5,80","5,90","6,05")):
    files=[fixture(start=dia,preco=preco)
           for dia,preco in zip(semanas,precos)]
    links="".join(f'<a href="{f["arquivo_url"]}/view">link municipal</a>'
                  for f in files)
    html=("<html><body><h1>Indice ANP - somente teste</h1><p>Legenda "
          "da pesquisa semanal sintética para validação sem dados reais.</p>"
          +links+"</body></html>").encode()
    return html, {f["arquivo_url"]: f["xlsx"] for f in files}


@unittest.skipIf(Workbook is None,"openpyxl não instalado")
class TestColetaANPLPCE2E(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        iniciar_staging(self.db)
        self.html,self.planilhas=lote()

    def run_lote(self,**kwargs):
        return coletar_lpc(
            self.db,indice_bytes=self.html,arquivos_locais=self.planilhas,
            ano=2026,limite_semanas=3,raw_dir=self.root,
            esperar_segundos=0,**kwargs,
        )

    def test_indice_xlsx_raw_sqlite_tendencia_três_semanas(self):
        result=self.run_lote()
        self.assertEqual(result["status"],"LOTE_COMPLETO")
        self.assertEqual(result["edicoes_integradas"],3)
        self.assertEqual(result["edicoes_novas"],3)
        self.assertEqual(result["observacoes_integradas"],6)
        self.assertFalse(result["publicavel"])
        self.assertFalse(result["arquivos_reais_baixados"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_edicoes").fetchone()[0],3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_observacoes").fetchone()[0],6)
        self.assertEqual(len(list((self.root/"planilhas").glob("*.xlsx"))),3)
        self.assertEqual(len(list((self.root/"indices").glob("*.html"))),1)
        indicador=tendencia_diesel_preliminar(
            self.db,municipio="SINOP",produto="DIESEL S10",
            as_of="2026-11-01T00:00:00+00:00")
        self.assertEqual(indicador["status"],"COMPARACAO_PRELIMINAR")
        self.assertEqual(indicador["direcao_observada"],"ALTA")
        self.assertEqual(indicador["semana_atual"],"2026-10-17")
        self.assertEqual(indicador["semana_anterior"],"2026-10-10")
        self.assertEqual(indicador["preco_revenda_atual_rs_l"],"6.05")
        self.assertEqual(indicador["variacao_absoluta_rs_l"],"0.15")
        self.assertFalse(indicador["inferir_frete"])
        self.assertFalse(indicador["publicavel"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='anp_semanal_edicoes'"
        ).fetchone()[0],0)

    def test_cenario_de_custo_liga_diesel_sem_confundir_com_frete(self):
        self.run_lote()
        resposta=impacto_diesel_anp_preliminar(
            self.db, municipio="SINOP",produto="DIESEL S10",
            as_of="2026-11-01T00:00:00+00:00",
            distancia_operacional_km=Decimal("700"),
            consumo_estimado_l_km=Decimal("0.4"),
            carga_por_viagem_t=Decimal("30"),
            distancia_validada=True,premissas_documentadas=True,
        )
        self.assertEqual(resposta["status"],"CENARIO_HIPOTETICO_PRELIMINAR")
        self.assertEqual(Decimal(resposta["variacao_custo_combustivel_brl_t"]),Decimal("1.40"))
        self.assertEqual(resposta["repasse_ao_frete"],"INDETERMINADO")
        self.assertFalse(resposta["frete_negociado"])
        self.assertFalse(resposta["frete_anunciado"])
        self.assertFalse(resposta["publicavel"])
        self.assertFalse(resposta["dados_homologados"])
        self.assertEqual(resposta["semana_atual"],"2026-10-17")
        self.assertEqual(len(resposta["sha256_atual"]),64)

    def test_cenario_de_custo_sem_series_suficientes_bloqueia(self):
        entrada=fixture(start=date(2026,10,11))
        _,files=lote(semanas=(date(2026,10,11),),precos=("6,02",))
        html=("<html><body><p>Índice ANP fictício para cenário insuficiente</p>"
              '<a href="'+entrada["arquivo_url"]+'">planilha</a></body></html>').encode()
        coletar_lpc(self.db,indice_bytes=html,arquivos_locais=files,
                   ano=2026,esperar_segundos=0)
        resposta=impacto_diesel_anp_preliminar(
            self.db,municipio="SINOP",produto="DIESEL S10",
            as_of="2026-11-01T00:00:00+00:00",
            distancia_operacional_km=Decimal("700"),
            consumo_estimado_l_km=Decimal("0.4"),
            carga_por_viagem_t=Decimal("30"),
            distancia_validada=True,premissas_documentadas=True,
        )
        self.assertEqual(resposta["status"],"INSUFICIENTE_PARA_CENARIO_DE_CUSTO")
        self.assertEqual(resposta["repasse_ao_frete"],"INDETERMINADO")
        self.assertNotIn("variacao_custo_combustivel_brl_t",resposta)

    def test_qualidade_revela_cobertura_semana_sem_raw_e_revisao(self):
        result=coletar_lpc(
            self.db,indice_bytes=self.html,arquivos_locais=self.planilhas,
            ano=2026,limite_semanas=3,esperar_segundos=0,
        )
        self.assertEqual(result["status"],"LOTE_COMPLETO")
        qa=painel_qualidade_lpc(
            self.db,as_of="2026-11-01T00:00:00+00:00")
        self.assertEqual(qa["semanas_unicas"],3)
        self.assertEqual(qa["edicoes_distintas"],3)
        self.assertEqual(qa["edicoes_sem_raw_arquivado"],3)
        self.assertEqual(qa["semana_mais_recente"],"2026-10-17")
        self.assertEqual(qa["semanas_faltantes_entre_extremos"],[])
        self.assertEqual(qa["semanas_com_revisoes"],[])
        self.assertFalse(qa["publicavel"])

    def test_qualidade_assinala_semana_faltante_e_revisoes(self):
        html,files=lote(semanas=(date(2026,9,27),date(2026,10,11)),
                        precos=("5,80","6,05"))
        coletar_lpc(self.db,indice_bytes=html,arquivos_locais=files,
                   ano=2026,esperar_segundos=0)
        revised=fixture(start=date(2026,10,11),preco="6,26")
        files[revised["arquivo_url"]]=revised["xlsx"]
        coletar_lpc(self.db,indice_bytes=html,arquivos_locais=files,
                   ano=2026,esperar_segundos=0)
        qa=painel_qualidade_lpc(
            self.db,as_of="2026-11-01T00:00:00+00:00")
        self.assertEqual(qa["semanas_unicas"],2)
        self.assertEqual(qa["edicoes_distintas"],3)
        self.assertEqual(qa["semanas_faltantes_entre_extremos"],
                         ["2026-10-10"])
        self.assertEqual(qa["semanas_com_revisoes"],["2026-10-17"])

    def test_recoleta_preserva_edicoes_e_cria_capturas(self):
        self.run_lote()
        resultado=self.run_lote()
        self.assertEqual(resultado["edicoes_novas"],0)
        self.assertEqual(resultado["edicoes_integradas"],3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_edicoes").fetchone()[0],3)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_observacoes").fetchone()[0],6)
        self.assertGreaterEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_capturas").fetchone()[0],3)

    def test_correcao_de_arquivo_mesma_semana_preserva_duas_vintages(self):
        self.run_lote()
        novo=fixture(start=date(2026,10,11),preco="6,25")
        self.planilhas[novo["arquivo_url"]]=novo["xlsx"]
        result=self.run_lote()
        self.assertEqual(result["edicoes_novas"],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_edicoes").fetchone()[0],4)
        indicator=tendencia_diesel_preliminar(
            self.db,municipio="SINOP",produto="DIESEL S10",
            as_of="2026-11-01T00:00:00+00:00")
        self.assertEqual(indicator["status"],
                         "REVISOES_DIVERGENTES_NAO_SELECIONADAS")
        self.assertNotIn("variacao_percentual",indicator)

    def test_xlsx_da_semana_errada_nao_entra_e_lote_e_parcial(self):
        url=fixture(start=date(2026,10,11))["arquivo_url"]
        mal=fixture(start=date(2026,10,11),
                    periodo_xlsx=date(2026,10,4),preco="6,55")
        self.planilhas[url]=mal["xlsx"]
        result=self.run_lote()
        self.assertEqual(result["status"],"LOTE_PARCIAL")
        self.assertEqual(result["edicoes_integradas"],2)
        self.assertEqual(len(result["erros"]),1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_lpc_staging_edicoes").fetchone()[0],2)
        indicator=tendencia_diesel_preliminar(
            self.db,municipio="SINOP",produto="DIESEL S10",
            as_of="2026-11-01T00:00:00+00:00")
        self.assertEqual(indicator["status"],"COMPARACAO_PRELIMINAR")
        self.assertEqual(indicator["semana_atual"],"2026-10-10")

    def test_semana_faltante_impede_tendencia(self):
        html,planilhas=lote(semanas=(date(2026,9,27),date(2026,10,11)),
                            precos=("5,80","6,05"))
        result=coletar_lpc(
            self.db, indice_bytes=html,arquivos_locais=planilhas,
            ano=2026,limite_semanas=3,esperar_segundos=0,
        )
        self.assertEqual(result["status"],"LOTE_COMPLETO")
        trend=tendencia_diesel_preliminar(
            self.db,municipio="SINOP",produto="DIESEL S10",
            as_of="2026-11-01T00:00:00+00:00")
        self.assertEqual(trend["status"],"SEMANAS_NAO_CONSECUTIVAS")

    def test_coletor_nao_supoe_link_que_nao_consta_do_indice(self):
        url=fixture(start=date(2026,10,25))["arquivo_url"]
        self.assertNotIn(url,self.planilhas)
        self.assertEqual(self.run_lote()["edicoes_integradas"],3)

    def test_https_pedido_real_com_abridor_falso_sem_redirect(self):
        from nivon.anp_indice_lpc import URL_INDICE
        res={URL_INDICE:Resposta(URL_INDICE,self.html,"text/html; charset=utf-8")}
        for url,body in self.planilhas.items():
            dl=url+"/@@download/file"
            res[dl]=Resposta(
                dl,body,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        mock=AberturaFake(res)
        done=coletar_lpc(
            self.db,ano=2026,limite_semanas=3,abridor=mock,
            esperar_segundos=0,raw_dir=self.root,
        )
        self.assertEqual(done["status"],"LOTE_COMPLETO")
        self.assertTrue(done["arquivos_reais_baixados"])
        self.assertEqual(len(mock.chamadas),4)
        self.assertEqual(mock.chamadas[0],URL_INDICE)
        self.assertTrue(all(x.startswith("https://www.gov.br/anp/")
                            for x in mock.chamadas))

    def test_http_nao_aceita_redirecionamento_waf_ou_xml(self):
        from nivon.anp_indice_lpc import URL_INDICE
        for mime,final,data in (
            ("text/html","https://www.gov.br/fora",self.html),
            ("application/json",URL_INDICE,self.html),
            ("text/html",URL_INDICE,b"<html>WAF</html>"),
        ):
            fake=AberturaFake({
                URL_INDICE:Resposta(URL_INDICE,data,mime,final_url=final)})
            with self.subTest(mime=mime,final=final,data=data[:10]):
                if data==b"<html>WAF</html>":
                    with self.assertRaises(ErroColetaANP):
                        obter_documento(URL_INDICE,tipo="HTML",abridor=fake)
                elif mime=="application/json" or final!=URL_INDICE:
                    with self.assertRaises(ErroColetaANP):
                        obter_documento(URL_INDICE,tipo="HTML",abridor=fake)

    def test_arquivamento_raw_hash_nao_permite_modificar_versao(self):
        self.run_lote()
        file=next((self.root/"planilhas").glob("*.xlsx"))
        original=file.read_bytes()
        file.write_bytes(b"PK__ADULTERADO")
        result=self.run_lote()
        self.assertEqual(result["status"],"LOTE_PARCIAL")
        self.assertTrue(result["erros"])
        self.assertNotEqual(file.read_bytes(),original)

    def test_cli_local_roda_integralmente_e_consulta_preview(self):
        pasta=self.root/"entradas"
        pasta.mkdir()
        (self.root/"indice_local.html").write_bytes(self.html)
        for url,body in self.planilhas.items():
            (pasta / url.split("/")[-1]).write_bytes(body)
        arquivo_sqlite=self.root/"anp.sqlite"
        output=io.StringIO()
        with redirect_stdout(output):
            rc=main([
                "--modo","arquivos","--ano","2026","--db",str(arquivo_sqlite),
                "--raw-dir",str(self.root),"--indice",str(self.root/"indice_local.html"),
                "--pasta-arquivos",str(pasta),"--ultimas","3",
            ])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(output.getvalue())["edicoes_integradas"],3)
        output=io.StringIO()
        with redirect_stdout(output):
            rc=main([
                "--modo","consulta","--db",str(arquivo_sqlite),
                "--municipio","SINOP","--produto","DIESEL S10",
                "--as-of","2026-11-01T00:00:00+00:00",
            ])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(output.getvalue())["direcao_observada"],"ALTA")
        output=io.StringIO()
        with redirect_stdout(output):
            rc=main(["--modo","status","--db",str(arquivo_sqlite),
                     "--as-of","2026-11-01T00:00:00+00:00"])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(output.getvalue())["semanas_unicas"],3)
        self.assertEqual(json.loads(output.getvalue())["edicoes_sem_raw_arquivado"],0)


if __name__ == "__main__":
    unittest.main()
