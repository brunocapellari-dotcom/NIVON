import unittest
from nivon.mdic_manifesto import catalogar_arquivos_mdic,selecionar_incremental,ErroManifestoMDIC
BASE="https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/"
def ancoras(ano):
    return "".join([
      f'<a href="{BASE}ncm/EXP_{ano}.csv">EXP</a>',
      f'<a href="{BASE}ncm/IMP_{ano}.csv">IMP</a>',
      f'<a href="{BASE}mun/EXP_{ano}_MUN.csv">EXP_MUN</a>',
      f'<a href="{BASE}mun/IMP_{ano}_MUN.csv">IMP_MUN</a>',
    ])
def html(*anos):
    return ("<html>"+ "".join(ancoras(a) for a in anos)+"</html>").encode()
class TestMDICManifesto(unittest.TestCase):
    def test_links_anuais_separados_direcao_ncm_municipio(self):
        r=catalogar_arquivos_mdic(html(2025,2026),ano_inicial=2025,ano_final=2026)
        self.assertEqual(r["quantidade"],8)
        self.assertEqual(len(r["ausentes"]),0)
        self.assertFalse(r["recurso_coletado"])
        self.assertFalse(r["coleta_automatica_ativada"])
        self.assertIn("EXP_2025.csv",next(x["url"] for x in r["arquivos"]
                                           if x["ano"]==2025 and x["granularidade"]=="NCM"
                                           and x["direcao"]=="EXPORTACAO"))
    def test_falha_ano_ausente_nunca_inventa_url(self):
        with self.assertRaises(ErroManifestoMDIC):
            catalogar_arquivos_mdic(html(2025),ano_inicial=2025,ano_final=2026)
        r=catalogar_arquivos_mdic(html(2025),ano_inicial=2025,ano_final=2026,exigir_completo=False)
        self.assertEqual(len(r["ausentes"]),4)
        self.assertEqual(r["quantidade"],4)
    def test_host_nao_oficial_e_caminho_falso_excluidos(self):
        injected=b'<html><a href="https://evil.example/balanca/bd/comexstat-bd/ncm/EXP_2026.csv">fake</a></html>'
        with self.assertRaises(ErroManifestoMDIC):
            catalogar_arquivos_mdic(injected,ano_inicial=2026,ano_final=2026)
    def test_arquivo_consolidado_extinto_nao_usado(self):
        injected=b'<html><a href="https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/ncm/EXP_COMPLETA.zip">old</a></html>'
        r=catalogar_arquivos_mdic(injected,ano_inicial=2026,ano_final=2026,exigir_completo=False)
        self.assertEqual(r["quantidade"],0)
    def test_duplicidade_bloqueada(self):
        doc=b"<html>"+ancoras(2026).encode()+ancoras(2026).encode()+b"</html>"
        with self.assertRaises(ErroManifestoMDIC):
            catalogar_arquivos_mdic(doc,ano_inicial=2026,ano_final=2026)
    def test_ano_antes_1997_e_futuro_rejeitados(self):
        for start,end in ((1996,2025),(2027,2027),(2026,2025)):
            with self.assertRaises(ErroManifestoMDIC):
                catalogar_arquivos_mdic(html(2025),ano_inicial=start,ano_final=end)
    def test_delta_nao_usa_hash_do_indice_como_hash_do_csv(self):
        r=catalogar_arquivos_mdic(html(2026),ano_inicial=2026,ano_final=2026)
        p=selecionar_incremental(r)
        self.assertEqual(len(p),4)
        self.assertTrue(all(x["delta"]=="VERSAO_ARQUIVO_A_VERIFICAR_POR_HASH_SHA256" for x in p))
