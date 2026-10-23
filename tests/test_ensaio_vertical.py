"""End-to-end CLI read-only e política de frescor, 100% fixtures."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime,timezone
from nivon.politica_frescura import aplicar_politica_frescura,ErroFrescura
from nivon.ensaio_vertical import executar,ErroEnsaio,main
from nivon.conab_agrobr import normalizar_progresso
from nivon.progresso_store import abrir_progresso,gravar_progresso
from nivon.portos_store import abrir_historico_portos,gravar_documento_porto
from nivon.portos import Programacao

AGORA="2026-10-20T12:00:00+00:00"
FONTE={
 "BCB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
 "CME":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
 "CONAB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
 "LINEUP_SANTOS":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
PACOTE={
 "fontes":FONTE,"noticias":[],
 "indicadores":[
   {"fonte_id":"BCB","secao":"CAMBIO","titulo":"Dólar PTAX teste",
    "valor":"R$ 5,00","fonte":"BCB fixture","referencia":AGORA},
   {"fonte_id":"CME","secao":"BOLSAS","titulo":"Soja CBOT teste",
    "valor":"1000 centavos/bu","fonte":"CME fixture","referencia":AGORA},
 ],
}


class TestFrescuraEEnsaio(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.p=Path(self.t.name)
        self.entrada=self.p/"input.json"
        self.escopo=self.p/"escopo.json"
        self.saida=self.p/"briefing.txt"
        self.entrada.write_text(json.dumps(PACOTE),encoding="utf-8")
        self.escopo.write_text('{"culturas":[],"portos":[]}',encoding="utf-8")

    def tearDown(self):
        self.t.cleanup()

    def args(self,*extra):
        return [
            "--entrada",str(self.entrada),"--contratos",str(self.escopo),
            "--gerado-em",AGORA,"--saida",str(self.saida),*extra,
        ]

    def test_politica_rejeita_cbots_antigos_e_futuros(self):
        item={"secao":"BOLSAS","referencia":"2026-10-01T12:00:00+00:00"}
        out=aplicar_politica_frescura([item],gerado_em=AGORA)
        self.assertEqual(out["recusados"][0]["motivo"],"REFERENCIA_VENCIDA")
        out2=aplicar_politica_frescura(
            [{**item,"referencia":"2026-10-21T12:00:00+00:00"}],
            gerado_em=AGORA)
        self.assertEqual(out2["recusados"][0]["motivo"],"REFERENCIA_FUTURA")

    def test_fecha_secao_sem_fuso(self):
        out=aplicar_politica_frescura(
            [{"secao":"CAMBIO","referencia":"2026-10-20T11:00:00"}],
            gerado_em=AGORA)
        self.assertEqual(out["recusados"][0]["motivo"],"REFERENCIA_INVALIDA")

    def test_limiares_fora_de_contrato_recusados(self):
        with self.assertRaises(ErroFrescura):
            aplicar_politica_frescura([],gerado_em=AGORA,
                                     limites={"BOLSAS":999})

    def test_cli_gera_arquivo_0600_sem_envio(self):
        r=executar(self.args())
        self.assertEqual(r["status"],"ENSAIO_OFFLINE_VALIDADO")
        self.assertFalse(r["transmissao_whatsapp"])
        self.assertTrue(self.saida.is_file())
        self.assertEqual(self.saida.stat().st_mode&0o777,0o600)
        self.assertIn("Soja CBOT teste",self.saida.read_text())

    def test_cli_nunca_sobrescreve_resultado(self):
        executar(self.args())
        with self.assertRaises(FileExistsError):
            executar(self.args())

    def test_cli_nao_inventa_cbot_vencida(self):
        pacote=json.loads(self.entrada.read_text())
        pacote["indicadores"][1]["referencia"]="2026-09-10T10:00:00+00:00"
        self.entrada.write_text(json.dumps(pacote))
        r=executar(self.args())
        self.assertEqual(r["status"],"BLOQUEADO_INDICADORES_ESSENCIAIS")
        self.assertFalse(self.saida.exists())

    def test_historico_ausente_retorna_bloqueio_sem_arquivo(self):
        self.escopo.write_text(json.dumps({"culturas":[{
          "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
          "uf":"MT","semana":"2026-10-16"}],"portos":[]}))
        r=executar(self.args())
        self.assertEqual(r["status"],"BLOQUEADO_HISTORICO_INCOMPLETO")
        self.assertFalse(self.saida.exists())

    def test_cli_ler_dados_versionados_sem_escrever_no_sqlite(self):
        url="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/teste"
        uporto="https://www.portodesantos.com.br/fixture"
        cpath=self.p/"conab.sqlite"
        ppath=self.p/"porto.sqlite"
        c=abrir_progresso(cpath)
        registros=normalizar_progresso([{
          "cultura":"Soja","safra":"2026/27","operacao":"Semeadura","uf":"MT",
          "semana_atual":"2026-10-16","pct_semana_atual":0.41,
        }],fonte_url=url,coletado_em=datetime(2026,10,19,12,tzinfo=timezone.utc),
           publicado_em="2026-10-18T12:00:00+00:00")
        gravar_progresso(c,registros,evidence_id="FIXTURE",direitos_confirmados=True)
        c.close()
        p=abrir_historico_portos(ppath)
        linha=Programacao(
            porto="SANTOS",navio="NAVIO TESTE",duv="D-1",imo="1111111",
            produto="SOJA",toneladas_programadas=50000,
            fonte=uporto,coletado_em="2026-10-20T11:00:00+00:00",
            status="PROGRAMADO")
        gravar_documento_porto(p,{
           "status":"EXTRAIDO_AGUARDA_HOMOLOGACAO","porto":"SANTOS",
           "fonte":uporto,"documento_sha256":hashlib.sha256(b"fixture").hexdigest(),
           "capturado_em":"2026-10-20T11:00:00+00:00","registros":[linha],
        },evidence_id="FIXTURE",direitos_confirmados=True)
        p.close()
        self.escopo.write_text(json.dumps({"culturas":[{
          "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
          "uf":"MT","semana":"2026-10-16"}],"portos":["SANTOS"]}))
        r=executar(self.args("--db-conab",str(cpath),"--db-portos",str(ppath)))
        self.assertEqual(r["status"],"ENSAIO_OFFLINE_VALIDADO")
        self.assertEqual(r["indicadores_historicos"],2)
        corpo=self.saida.read_text(encoding="utf-8")
        self.assertIn("41.0% informado",corpo)
        self.assertIn("Line-up SANTOS",corpo)
        self.assertIn("programadas",corpo)

    def test_arquivo_json_symlink_recusado(self):
        fake=self.p/"link.json"
        fake.symlink_to(self.entrada)
        args=self.args()
        args[1]=str(fake)
        with self.assertRaises(ErroEnsaio):
            executar(args)


if __name__=="__main__":
    unittest.main()
