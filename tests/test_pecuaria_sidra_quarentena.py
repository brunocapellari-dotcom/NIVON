"""E2E offline do coletor values-only. Nenhuma rede externa nos testes."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_quarentena import (
    executar_captura_values_quarentena,
    recuperar_values_quarentena, main,
)
from nivon.pecuaria_sidra_mapa_observado import contrato_sidra_observado


def transporte_sintetico(*,url,timeout,limite):
    tabela = url.split("/t/")[1].split("/")[0]
    especie = {"1092":"BOVINO","1093":"SUINO","1094":"FRANGO"}[tabela]
    mapa = contrato_sidra_observado(especie=especie,tabela_sidra=tabela)
    uf = "/n3/all/" in url
    header = {col: nome + " (Código)"
              for nome,col in mapa["dimensoes"].items()}
    header.update({"NC":"Nível Territorial (Código)","MN":"Unidade",
                   "V":"Valor"})
    dados=[]
    for variable, unid, val in (
        ("284","Cabeças","100"),
        ("285","Quilogramas","23000")):
        row={"NC":"3" if uf else "1","MN":unid,"V":val,
             mapa["dimensoes"]["territorio"]:"51" if uf else "1",
             mapa["dimensoes"]["periodo"]:"202602",
             mapa["dimensoes"]["variavel"]:variable}
        row.update({mapa["dimensoes"][key]:str(value)
                    for key,value in mapa["totais"].items()})
        dados.append(row)
    return {"status_http":200,"content_type":"application/json",
            "corpo":json.dumps([header,*dados],ensure_ascii=False).encode()}


class TestColetorValuesQuarentena(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.banco=Path(self.temp.name)/"sidra-quarentena.sqlite"

    def executar_simulado(self,**overrides):
        kw={"periodo":"202602","direitos_confirmados":True,
            "transporte":transporte_sintetico}
        kw.update(overrides)
        return executar_captura_values_quarentena(**kw)

    def test_plano_nao_usa_rede_ou_banco(self):
        r=executar_captura_values_quarentena()
        self.assertEqual(r["status"],"PLANEJADO_SEM_REDE")
        self.assertEqual(len(r["url_previstas"]),6)
        self.assertFalse(self.banco.exists())

    def test_coleta_simulada_e2e_preview_sem_gravacao(self):
        r=self.executar_simulado()
        self.assertEqual(len(r["capturas"]),6)
        self.assertEqual(len(r["diagnosticos"]),3)
        self.assertTrue(all(x["linhas_vigentes"]==4
                            for x in r["diagnosticos"]))
        self.assertFalse(r["publicacao_permitida"])
        self.assertFalse(r["publicacao_historica_confirmada"])
        self.assertFalse(r["metadata_v3_confirmado"])
        self.assertFalse(r["consulta_externa_executada"])
        self.assertFalse(r["gravado"])
        self.assertFalse(self.banco.exists())
        json.dumps(r,ensure_ascii=False)

    def test_coleta_gravada_atomica_e_idempotencia_por_hash(self):
        a=self.executar_simulado(banco=self.banco,gravar=True)
        self.assertEqual(len(set(a["ids"])),6)
        b=self.executar_simulado(banco=self.banco,gravar=True)
        self.assertEqual(b["ids"],a["ids"])
        with sqlite3.connect(self.banco) as cx:
            self.assertEqual(cx.execute(
                "SELECT COUNT(*) FROM valores_pecuaria_quarentena").fetchone()[0],6)
        cap=recuperar_values_quarentena(banco=self.banco,id_captura=a["ids"][0])
        self.assertEqual(cap["especie"],"BOVINO")
        self.assertTrue(cap["bruto"].startswith(b"["))
        self.assertFalse(cap["homologado"])

    def test_falha_apos_cinco_consultas_nao_deixa_residuo(self):
        contagem=[0]
        def falha(*,url,timeout,limite):
            contagem[0]+=1
            if contagem[0]==6:
                return {"status_http":429,"content_type":"text/plain",
                        "corpo":b"rate limited"}
            return transporte_sintetico(url=url,timeout=timeout,limite=limite)
        with self.assertRaisesRegex(DadoInvalido,"HTTP"):
            self.executar_simulado(banco=self.banco,gravar=True,transporte=falha)
        self.assertEqual(contagem[0],6)
        self.assertFalse(self.banco.exists())

    def test_sem_direitos_bloqueia_captura_e_escrita(self):
        for gr in (False,True):
            with self.assertRaises(PermissionError):
                self.executar_simulado(direitos_confirmados=False,gravar=gr,banco=self.banco)
            self.assertFalse(self.banco.exists())

    def test_periodo_nao_homologado_falha_fechado(self):
        for periodo in ("199701","202603","202601","202602/redirect"):
            with self.assertRaises(DadoInvalido):
                self.executar_simulado(periodo=periodo)

    def test_bytes_adulterados_nao_recuperados(self):
        r=self.executar_simulado(banco=self.banco,gravar=True)
        with sqlite3.connect(self.banco) as cx:
            cx.execute("DROP TRIGGER pecuaria_quarentena_sem_update")
            cx.execute("UPDATE valores_pecuaria_quarentena SET bruto=? WHERE id=?",
                       (b'[]',r["ids"][0]))
        with self.assertRaisesRegex(DadoInvalido,"integridade"):
            recuperar_values_quarentena(banco=self.banco,id_captura=r["ids"][0])

    def test_consulta_read_only_nao_cria_banco(self):
        with self.assertRaisesRegex(DadoInvalido,"nao existe"):
            recuperar_values_quarentena(banco=self.banco,id_captura=1)
        self.assertFalse(self.banco.exists())

    def test_cli_sem_rede_nao_consulta_nem_arquiva(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out=StringIO()
        with redirect_stdout(out):
            rc=main(["--periodo","202602"])
        self.assertEqual(rc,0)
        plano=json.loads(out.getvalue())
        self.assertEqual(plano["status"],"PLANEJADO_SEM_REDE")
        self.assertFalse(self.banco.exists())


if __name__=="__main__":
    unittest.main()
