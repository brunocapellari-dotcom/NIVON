"use strict";

const fmt=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
function set(id,v){document.getElementById(id).textContent=v;}
async function carregar(){
  try{
    const r=await fetch('/api/v1/ferrovia',{cache:'no-store',credentials:'same-origin'});
    if(!r.ok)throw new Error('Consulta indisponível ('+r.status+').');
    const dados=await r.json();
    if(dados.estado!=='ANTT_SERIE_OBSERVADA_DECLARADA')throw new Error('Série não validada.');
    document.getElementById('estado').classList.remove('error');
    set('tu',fmt.format(dados.tu_acumuladas));
    set('od',fmt.format(dados.registros_acumulados));
    set('competencia',dados.ultima_competencia);
    set('atualizacao','Última coleta: '+dados.ultima_coleta_utc.slice(0,16).replace('T',' ')+' UTC');
    const chart=document.getElementById('chart'),rows=document.getElementById('linhas');
    chart.replaceChildren();rows.replaceChildren();
    const peak=Math.max(...dados.serie.map(x=>Number(x.toneladas_uteis)))||1;
    for(const a of dados.serie){
      const col=document.createElement('div');col.className='bar-col';
      const bar=document.createElement('div');bar.className='bar'+(a.parcial?' partial':'');
      bar.style.height=(Number(a.toneladas_uteis)/peak*190)+'px';
      bar.title=a.ano+': '+fmt.format(a.toneladas_uteis)+' TU';
      const yr=document.createElement('div');yr.className='year';yr.textContent=a.ano;
      col.append(bar,yr);chart.append(col);
      const tr=document.createElement('tr');
      for(const v of [String(a.ano),fmt.format(a.toneladas_uteis),
                      fmt.format(a.registros),a.ultima_competencia,a.arquivo_sha256]){
        const td=document.createElement('td');td.textContent=v;tr.append(td);
      }rows.append(tr);
    }
    set('estado',dados.freshness.estado==='SOURCE_LAG'
      ?'FONTE DEFASADA · Competência '+dados.ultima_competencia+' · Coleta recente não significa dado novo.'
      :'DADOS DECLARADOS DA ANTT · Consulta real BigQuery · Última versão');
    for(const id of ['cards','serie','tabela'])document.getElementById(id).hidden=false;
  }catch(e){
    set('competencia','Sem dados disponíveis');set('atualizacao','Fonte e atualização não verificadas');
    for(const id of ['cards','serie','tabela'])document.getElementById(id).hidden=true;
    document.getElementById('chart').replaceChildren();document.getElementById('linhas').replaceChildren();
    const status=document.getElementById('estado');status.classList.add('error');
    set('estado','DADOS INDISPONÍVEIS: '+e.message+' Nenhum número foi estimado.');
  }
}
document.getElementById('atualizar').addEventListener('click',carregar);
carregar();
