"""Consulta científica MDIC fertilizantes, sem publicar volumes/FOB não homologados."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from nivon.mdic_importacao import COLUNAS
from nivon.ingestao_mdic import ingerir_arquivo_mdic, _tabelas
from nivon.registro_snapshots import abrir_registro
from nivon.mdic_fertilizantes_asof import (
    resumo_mdic_fertilizante_asof, ErroVisaoFertilizantes,
)
from nivon.hermes_adapter import NivonProjectAdapter

CAT={"datasets":[{"id":"MDIC_COMEX_NCM","source_id":"MDIC",
                  "enabled":True,"collection_authorized":True}]}
RIGHTS={"MDIC_COMEX_NCM":{"status_direitos":"APROVADA",
                         "operacoes":["LEITURA"]}}
AGORA="2026-10-20T16:00:00+00:00"


def row(*,ncm="31021010",uf="MT",kg="2000",usd="800",month="09"):
    values={
        "CO_ANO":"2026","CO_MES":month,"CO_NCM":ncm,
        "CO_UNID":"10","CO_PAIS":"160","SG_UF_NCM":uf,
        "CO_VIA":"01","CO_URF":"081","QT_ESTAT":"1",
        "KG_LIQUIDO":kg,"VL_FOB":usd,"VL_FRETE":"300","VL_SEGURO":"12",
    }
    return ";".join(values[k] for k in COLUNAS)


class TestFertilizantesMDIC(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/"IMP_2026.csv"
        self.write()
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def write(self,usd="800",extra=""):
        body=";".join(COLUNAS)+"\n"+row(usd=usd)+"\n"
        if extra:body+=extra
        self.file.write_text(body,encoding="utf-8")

    def load(self,coleta="2026-10-20T14:00:00+00:00",
             tipo="REAL_AUTORIZADO"):
        sha=hashlib.sha256(self.file.read_bytes()).hexdigest()
        return ingerir_arquivo_mdic(
            self.db,CAT,caminho=self.file,
            ano=2026,direcao="IMPORTACAO",granularidade="NCM",
            codigos=frozenset({"31021010","31042090"}),
            coletado_em=coleta,sha256_esperado=sha,
            tipo=tipo,
            autorizacoes=(frozenset({"COLETA","ARMAZENAMENTO"})
                          if tipo=="REAL_AUTORIZADO" else frozenset()),
            evidencia_direitos=("DOC_FIXTURE_CONSENTIMENTO_TESTE"
                                if tipo=="REAL_AUTORIZADO" else None),
        )

    def read(self,when=AGORA,**kw):
        return resumo_mdic_fertilizante_asof(
            self.db,ncm="31021010",uf="MT",ano=2026,mes=9,
            gerado_em=when,leitura_autorizada=True,**kw)

    def test_importacao_fob_e_unidade_nao_preco_spot(self):
        self.load()
        r=self.read()
        self.assertEqual(r["status"],"ANALISE_MDIC_NAO_HOMOLOGADA")
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["enviar_whatsapp"])
        self.assertEqual(r["registro"]["produto"],"UREIA")
        self.assertEqual(r["registro"]["volume_t"],2.)
        self.assertEqual(r["registro"]["valor_fob_usd"],800)
        self.assertEqual(r["registro"]["valor_unitario_fob_usd_t"],400.)
        self.assertEqual(r["registro"]["uf_fiscal"],"MT")
        self.assertIn("NAO_PRECO_CFR",r["registro"]["tipo_valor"])
        self.assertIsNone(r["evidencia"]["publicacao"])

    def test_obs_posterior_corte_nao_visivel(self):
        self.load()
        self.assertEqual(
            self.read("2026-10-20T13:00:00+00:00")["status"],
            "SEM_SNAPSHOT_REAL_ASOF")

    def test_fonte_sintetica_nao_se_torna_observacao_real(self):
        self.load(tipo="SINTETICO")
        self.assertEqual(self.read()["status"],"SEM_SNAPSHOT_REAL_ASOF")

    def test_ncm_fora_da_cobertura_nao_virou_zero(self):
        self.load()
        v=resumo_mdic_fertilizante_asof(
            self.db,ncm="31053090",uf="MT",
            ano=2026,mes=9,gerado_em=AGORA,leitura_autorizada=True)
        self.assertEqual(v["status"],"NCM_FORA_DA_COBERTURA_DO_SNAPSHOT")

    def test_ncm_coberto_sem_linha_nao_vira_zero(self):
        self.load()
        v=resumo_mdic_fertilizante_asof(
            self.db,ncm="31042090",uf="MT",
            ano=2026,mes=9,gerado_em=AGORA,leitura_autorizada=True)
        self.assertEqual(v["status"],"SEM_RECORTE_NO_SNAPSHOT")

    def test_sem_direito_de_leitura_nega_antes_db(self):
        self.assertEqual(resumo_mdic_fertilizante_asof(
            self.db,ncm="31021010",uf="MT",
            ano=2026,mes=9,gerado_em=AGORA)["status"],
            "BLOQUEADO_DIREITOS_LEITURA")

    def test_revisao_temporal_respeita_asof(self):
        self.load()
        self.write(usd="900")
        self.load(coleta="2026-10-21T13:00:00+00:00")
        self.assertEqual(self.read()["registro"]["valor_fob_usd"],800)
        self.assertEqual(
            self.read("2026-10-22T14:00:00+00:00")["registro"]["valor_fob_usd"],900)

    def test_edicoes_concorrentes_no_mesmo_instante_bloqueadas(self):
        self.load()
        self.write(usd="900")
        self.load()
        self.assertEqual(self.read()["status"],"VINTAGES_CONFLITANTES")

    def test_unidade_nao_soma_uf_diferente_ou_ncm_distinto(self):
        self.write(extra=row(ncm="31042090",uf="MT",kg="1000",usd="10")+"\n"+
                   row(uf="SP",kg="3000",usd="20")+"\n")
        self.load()
        self.assertEqual(self.read()["registro"]["valor_fob_usd"],800)
        self.assertEqual(self.read()["registro"]["volume_t"],2.0)

    def test_data_futura_e_ncm_invalidos_recusados(self):
        self.load()
        with self.assertRaises(ErroVisaoFertilizantes):
            resumo_mdic_fertilizante_asof(
                self.db,ncm="31021010",uf="MT",ano=2026,mes=12,
                gerado_em=AGORA,leitura_autorizada=True)
        with self.assertRaises(ErroVisaoFertilizantes):
            resumo_mdic_fertilizante_asof(
                self.db,ncm="12019000",uf="MT",ano=2026,mes=9,
                gerado_em=AGORA,leitura_autorizada=True)


class TestHermesFertilizantes(unittest.IsolatedAsyncioTestCase):
    async def test_interface_readonly_sem_banco_e_sem_licenca(self):
        adapter=NivonProjectAdapter(autorizador=lambda _:True,fontes=RIGHTS)
        q={"gerado_em":AGORA,"ncm":"31021010","uf":"MT","ano":2026,"mes":9}
        r=await adapter.query("fertilizantes.importacao.read",q)
        self.assertEqual(r["status"],"SEM_HISTORICO")
        await adapter.capabilities()
        with self.assertRaises(PermissionError):
            await adapter.execute("fertilizantes.importacao.write",q)

    async def test_hermes_analise_sem_promover_para_briefing(self):
        db=abrir_registro(":memory:")
        try:
            _tabelas(db)
            adapter=NivonProjectAdapter(autorizador=lambda _:True,fontes=RIGHTS,mdic=db)
            out=await adapter.query("fertilizantes.importacao.read",{
                "gerado_em":AGORA,"ncm":"31021010","uf":"MT",
                "ano":2026,"mes":9})
            self.assertEqual(out["status"],"SEM_SNAPSHOT_REAL_ASOF")
            self.assertFalse(out["publicavel"])
            # Não existe forma de pedir publicação nesse contrato.
            with self.assertRaises(ValueError):
                await adapter.query("fertilizantes.importacao.read",{
                    "gerado_em":AGORA,"ncm":"31021010","uf":"MT",
                    "ano":2026,"mes":9,"enviar_whatsapp":True})
        finally:
            db.close()


if __name__=="__main__":
    unittest.main()
