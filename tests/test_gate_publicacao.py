import unittest
from datetime import datetime, timedelta, timezone
from nivon.gate_publicacao import avaliar_prontidao_edicao, BLOCOS_OBRIGATORIOS

AGORA="2026-10-20T09:00:00-03:00"
def cobertura():
    return {b:{"estado":"VALIDADO","fonte_verificada":True,
               "direitos_aprovados":True,"referencia_em":AGORA}
            for b in BLOCOS_OBRIGATORIOS}
def avaliar(**changes):
    args={"edicao":{"estado":"EDICAO_OFFLINE_PREPARADA_SEM_ENVIO","enviado":False},
          "gerado_em":AGORA,"cobertura":cobertura(),"destinos_opt_in":1,
          "canal_homologado":True,"aprovacao_editorial":True}
    args.update(changes)
    return avaliar_prontidao_edicao(**args)

class TestGatePublicacao(unittest.TestCase):
    def test_todos_gates_documentados(self):
        self.assertTrue(avaliar()["pronto_para_envio"])
    def test_sem_cobertura_reprova(self):
        self.assertFalse(avaliar(cobertura={})["pronto_para_envio"])
    def test_sem_opt_in_reprova(self):
        self.assertIn("SEM_DESTINATARIOS_COM_CONSENTIMENTO",avaliar(destinos_opt_in=0)["motivos"])
    def test_sem_canal_reprova(self):
        self.assertFalse(avaliar(canal_homologado=False)["pronto_para_envio"])
    def test_sem_aprovacao_reprova(self):
        self.assertFalse(avaliar(aprovacao_editorial=False)["pronto_para_envio"])
    def test_fonte_sem_direitos_reprova(self):
        c=cobertura();c["CAMBIO"]["direitos_aprovados"]=False
        self.assertIn("PROVENIENCIA_OU_DIREITOS:CAMBIO",avaliar(cobertura=c)["motivos"])
    def test_fonte_antiga_reprova(self):
        c=cobertura();c["ENERGIA"]["referencia_em"]="2026-10-01T09:00:00-03:00"
        self.assertIn("REFERENCIA_DESATUALIZADA:ENERGIA",avaliar(cobertura=c)["motivos"])
    def test_referencia_futura_reprova(self):
        c=cobertura();c["CHICAGO"]["referencia_em"]="2026-10-21T09:00:00-03:00"
        self.assertFalse(avaliar(cobertura=c)["pronto_para_envio"])
    def test_edicao_nao_preparada_reprova(self):
        self.assertFalse(avaliar(edicao={"estado":"ERRO","enviado":False})["pronto_para_envio"])
    def test_sem_entrada_reprova(self):
        self.assertFalse(avaliar(edicao=None,cobertura=None)["pronto_para_envio"])
if __name__=="__main__":unittest.main()
