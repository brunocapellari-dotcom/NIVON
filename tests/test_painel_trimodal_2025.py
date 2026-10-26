import unittest
from nivon.painel_trimodal_2025 import preparar_painel,HF_COMMIT
from nivon.antaq_replica_hidrovia import ErroReplicaANTAQ

def base():
    return {
        "ano":2025,
        "estado":"PAINEL_MULTIMODAL_2025_DADOS_SEPARADOS_COM_PROVENIENCIA",
        "totais_das_modalidades_somaveis":False,
        "escopo_top16_rodoviario_toneladas":"98170287",
        "polos":[{"polo_id":str(i)} for i in range(9)],
        "rodovia_rgi_fluxos_top16":[{"origem_rgi":"Rondonópolis","produto":None}],
    }

def fonte():
    return {
        "estado":"REPLICA_ANTAQ_2025_APENAS_CAMADA_SECUNDARIA",
        "hf_revision":HF_COMMIT,"ano":2025,
        "fonte_direta_antaq":False,"linhas_hidroviarias":27,
        "snapshot_id":"a"*64,"sha256_hidrovia":"b"*64,"sha256_carga":"c"*64,
        "toneladas_navegacao_interior_idcarga_unica":"92431869.759",
        "toneladas_com_hidrovia_identificada_idcarga_unica":"53250176.855",
    }

def rows():
    f=fonte()
    out=[]
    for rio in ("Hidrovia do Madeira","Hidrovia do Tapajós","Hidrovia do Baixo Amazonas"):
        for direcao in ("Embarcados","Desembarcados","Outros"):
            for produto in ("SOJA","MILHO","FARELO_DE_SOJA"):
                out.append({
                    "ano":2025,"hf_revision":HF_COMMIT,"snapshot_id":f["snapshot_id"],
                    "sha256_hidrovia":f["sha256_hidrovia"],
                    "sha256_carga":f["sha256_carga"],
                    "dados_oficiais_antaq":False,
                    "aditividade_entre_rios":False,"transbordo_confirmado":False,
                    "navegacao":"Interior","hidrovia":rio,"sentido":direcao,
                    "grupo_produto":produto,"toneladas_trechos":"12345.456",
                })
    return out

class Trimodal(unittest.TestCase):
    def test_retorna_modalidades_separadas_sem_gerar_total(self):
        resultado=preparar_painel(base(),rows(),fonte())
        self.assertEqual(resultado["hidrovia_grupos"],27)
        self.assertEqual(len(resultado["polos_rodovia_e_ferrovia"]),9)
        self.assertFalse(resultado["gates"]["somar_rodovia_ferrovia_hidrovia"])
        self.assertFalse(resultado["gates"]["somar_hidrovias_entre_si"])
        self.assertFalse(resultado["gates"]["aprovar_hidrovia_como_oficial"])
        self.assertFalse(resultado["gates"]["gravar_google_cloud"])
        self.assertFalse(resultado["gates"]["inferir_transbordos"])
        self.assertFalse(any(x["transbordo_confirmado"] for x in resultado["hidrovia_recortes"]))
        self.assertNotIn("total_multimodal_toneladas",resultado)

    def test_bloquear_dado_terceiro_promovido_a_oficial(self):
        dados=rows()
        dados[0]["dados_oficiais_antaq"]=True
        with self.assertRaisesRegex(ErroReplicaANTAQ,"comparacao"):
            preparar_painel(base(),dados,fonte())

    def test_bloquear_duplicacao_de_trechos(self):
        dados=rows()
        dados[-1]=dados[0].copy()
        with self.assertRaisesRegex(ErroReplicaANTAQ,"duplicado"):
            preparar_painel(base(),dados,fonte())

    def test_fonte_ou_universo_incompleto_bloqueia(self):
        for mut in ("fonte","rodovia","hvalores","grupos"):
            r=rows()
            f=fonte()
            a=base()
            if mut=="fonte":f["hf_revision"]="0"*40
            elif mut=="rodovia":a["escopo_top16_rodoviario_toneladas"]="0"
            elif mut=="hvalores":r[0]["toneladas_trechos"]="-2"
            elif mut=="grupos":r.pop()
            with self.subTest(case=mut):
                with self.assertRaises(ErroReplicaANTAQ):
                    preparar_painel(a,r,f)

if __name__=="__main__":
    unittest.main()
