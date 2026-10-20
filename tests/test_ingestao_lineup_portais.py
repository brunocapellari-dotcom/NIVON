import hashlib
import unittest
from copy import deepcopy

from nivon.ingestao_lineup_portais import contrato_fonte, processar_snapshot, coletar_autorizado
from nivon.lineup_portais import ErroPortal


class TestIngestaoLineupPortais(unittest.TestCase):
    def snapshot(self):
        corpo=(b"<h3>Navios Atracados</h3><table><tr><th>Navio</th><th>IMO</th>"
               b"<th>Carga</th><th>Qtd.Carga</th><th>Ultima Atualizacao</th></tr>"
               b"<tr><td>NAVIO SINTETICO</td><td>9464405</td><td>SOJA</td>"
               b"<td>50.000</td><td>19/10/26</td></tr></table>")
        fonte=contrato_fonte("ITAQUI")
        return {"fonte_id":fonte.fonte_id, "url":fonte.url, "mime":"text/html",
                "conteudo":corpo,"sha256":hashlib.sha256(corpo).hexdigest(),
                "capturado_em":"2026-10-19T18:00:00Z"}

    def test_pipeline_sem_publicar(self):
        res=processar_snapshot("ITAQUI",self.snapshot())
        self.assertEqual(res["integridade"],"SHA256_CONFERIDO")
        self.assertEqual(res["registros"][0]["navio"],"NAVIO SINTETICO")
        self.assertFalse(res["publicacao_habilitada"])
        self.assertFalse(res["registros"][0]["apto_briefing"])

    def test_hash_adulterado_rejeita(self):
        s=self.snapshot()
        s["conteudo"]+=b"ADULTERADO"
        with self.assertRaises(ErroPortal):
            processar_snapshot("ITAQUI",s)

    def test_fonte_ou_mime_trocados_rejeita(self):
        s=self.snapshot()
        s["url"]="https://malicioso.example/"
        with self.assertRaises(ErroPortal):
            processar_snapshot("ITAQUI",s)
        s=self.snapshot()
        s["mime"]="application/json"
        with self.assertRaises(ErroPortal):
            processar_snapshot("ITAQUI",s)

    def test_rede_sem_direitos_proibida(self):
        class NaoAbrir:
            def open(self,*args,**kwargs):
                raise AssertionError("não deveria acessar rede")
        with self.assertRaises(PermissionError):
            coletar_autorizado("ITAQUI",direitos_comprovados=True,abridor=NaoAbrir())

    def test_contrato_itaqui_permanece_desativado(self):
        f=contrato_fonte("ITAQUI")
        self.assertEqual(f.status_direitos,"PENDENTE")
        self.assertNotIn("COLETA",f.operacoes_permitidas)


if __name__=="__main__":
    unittest.main()
