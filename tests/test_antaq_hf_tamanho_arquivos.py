import unittest
from types import SimpleNamespace
from nivon.antaq_hf_tamanho_arquivos import inspecionar_siblings,ARQUIVOS

def itens(a,b):
    return [SimpleNamespace(rfilename=ARQUIVOS["hidrovia"],size=a),
            SimpleNamespace(rfilename=ARQUIVOS["carga"],size=b)]
class HFTeste(unittest.TestCase):
    def test_valores_pequenos_aprovados_so_para_tentativa(self):
        d=inspecionar_siblings(itens(10_000,12_000))
        self.assertTrue(d["apto_para_tentativa_local"])
        self.assertFalse(d["gravacao_cloud"])
        self.assertFalse(d["microdados_oficiais_antaq"])
    def test_tamanho_excessivo_nao_baixa(self):
        d=inspecionar_siblings(itens(20_000,70_000_000))
        self.assertFalse(d["apto_para_tentativa_local"])
        self.assertFalse(d["arquivos"][1]["tamanho_aprovado"])
    def test_arquivo_ausente_falha(self):
        with self.assertRaisesRegex(ValueError,"AUSENTE"):
            inspecionar_siblings(itens(123,456)[:1])
    def test_tamanho_nao_declarado_falha(self):
        with self.assertRaisesRegex(ValueError,"COMPROVADO"):
            inspecionar_siblings(itens(None,123))
if __name__=="__main__":
    unittest.main()
