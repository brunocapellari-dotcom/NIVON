// Piloto separado do terminal NIVON. Requer magnitude-core previamente instalado
// em runner controlado e modelo credenciado/autorizado. Nenhuma instalação automática.
// Uso: NIVON_AI_NETWORK_APPROVED=true NIVON_AI_EXTERNAL_APPROVED=true
//      NIVON_AI_APPROVED_HOSTS=exemplo.gov.br node scripts/nivon_magnitude_piloto.mjs https://exemplo.gov.br
import { startBrowserAgent } from 'magnitude-core';
const url = process.argv[2];
const hosts = (process.env.NIVON_AI_APPROVED_HOSTS ?? '').split(',').map(x => x.trim().toLowerCase());
if (process.env.NIVON_AI_NETWORK_APPROVED !== 'true' ||
    process.env.NIVON_AI_EXTERNAL_APPROVED !== 'true') throw new Error('REDE_EXTERNA_NAO_AUTORIZADA');
let endereco;
try { endereco = new URL(url); } catch { throw new Error('URL_INVALIDA'); }
if (endereco.protocol !== 'https:' || endereco.username || endereco.password || endereco.port ||
    endereco.hash || !hosts.includes(endereco.hostname.toLowerCase())) throw new Error('DOMINIO_NAO_APROVADO');
const agent = await startBrowserAgent();
try {
  await agent.nav(url);
  // Somente observação; nenhuma ação de clicar, enviar, logar ou publicar.
  console.log(JSON.stringify({ capacidade: 'magnitude', origem: url,
    estado: 'NAVEGACAO_REALIZADA_SEM_VALIDACAO_DADOS', publicavel: false }));
} finally { await agent.stop(); }
