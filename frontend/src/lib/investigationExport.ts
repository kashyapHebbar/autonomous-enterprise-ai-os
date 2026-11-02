import type { Artifact, RunDetail } from '../types';
import { api } from '../api';
import { artifactFilename, artifactTitle } from './artifactGroups';

/** Simple ZIP (uncompressed STORE) writer. No runtime dependencies or external services. */
const encoder=new TextEncoder();
const MAX_FILE=12*1024*1024;
const MAX_PACKAGE=60*1024*1024;
function crc32(bytes:Uint8Array):number{let crc=0xffffffff;for(const byte of bytes){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return (crc^0xffffffff)>>>0;}
function u16(v:DataView,off:number,n:number){v.setUint16(off,n,true);}
function u32(v:DataView,off:number,n:number){v.setUint32(off,n>>>0,true);}
function safeName(text:string){return text.replace(/[\\/\x00-\x1F<>:"|?*]/g,'_').replace(/\.\./g,'_').replace(/^\.+/,'').trim().slice(0,100)||'result';}
function entry(name:string,data:Uint8Array){return {name:safeName(name),data};}
function makeZip(files:Array<{name:string;data:Uint8Array}>):Blob{
  const parts:BlobPart[]=[];const directory:BlobPart[]=[];let offset=0;let directoryBytes=0;
  for(const {name,data} of files){const nameBytes=encoder.encode(name);const checksum=crc32(data);const head=new Uint8Array(30+nameBytes.length);const h=new DataView(head.buffer);u32(h,0,0x04034b50);u16(h,4,20);u16(h,6,0x0800);u16(h,8,0);u32(h,14,checksum);u32(h,18,data.byteLength);u32(h,22,data.byteLength);u16(h,26,nameBytes.length);head.set(nameBytes,30);parts.push(head,new Uint8Array(data));const cent=new Uint8Array(46+nameBytes.length);const c=new DataView(cent.buffer);u32(c,0,0x02014b50);u16(c,4,20);u16(c,6,20);u16(c,8,0x0800);u16(c,10,0);u32(c,16,checksum);u32(c,20,data.byteLength);u32(c,24,data.byteLength);u16(c,28,nameBytes.length);u32(c,42,offset);cent.set(nameBytes,46);directory.push(cent);offset+=head.length+data.length;directoryBytes+=cent.length;}
  const end=new Uint8Array(22);const e=new DataView(end.buffer);u32(e,0,0x06054b50);u16(e,8,files.length);u16(e,10,files.length);u32(e,12,directoryBytes);u32(e,16,offset);return new Blob([...parts,...directory,end],{type:'application/zip'});
}
/** Download existing generated results. Never include the source CSV or analysis code. */
export async function downloadInvestigationPackage(run:RunDetail):Promise<number>{
  const selected=run.artifacts.filter(a=>a.type!=='dataset'&&a.type!=='code'&&['report','dashboard','chart','kpi_table','schema_profile','quality_report','evaluation'].includes(a.type)).slice(0,50);
  if(!selected.length)throw new Error('No downloadable results are available for this analysis.');
  const records:Array<{name:string;data:Uint8Array}>=[];
  const manifest:{name:string;run_id:string;created_at:string;source:string;included:Array<{title:string;filename:string;type:string;artifact_id:string;source_artifact_ids:string[]}>;excluded:string[]}={name:'AEAI OS — Investigation Results',run_id:run.id,created_at:new Date().toISOString(),source:'Saved generated artifacts. Does not contain original source data.',included:[],excluded:[]};
  let total=0;
  for(let i=0;i<selected.length;i++){
    const a:Artifact=selected[i];if(a.size_bytes!==null&&a.size_bytes>MAX_FILE){manifest.excluded.push(`${artifactTitle(a)} — exceeds size limit`);continue;}
    const response=await fetch(api.artifactUrl(run.id,a.id,true),{credentials:'same-origin'});
    if(!response.ok)throw new Error(`Cannot retrieve ${artifactTitle(a)} (HTTP ${response.status}). Please check your access permissions.`);
    const blob=await response.blob();if(blob.size>MAX_FILE){manifest.excluded.push(`${artifactTitle(a)} — exceeds size limit`);continue;}
    total+=blob.size;if(total>MAX_PACKAGE)throw new Error('Results exceed the 60 MB package limit. Download individual files instead.');
    const original=artifactFilename(a);const ext=original.match(/\.[a-z0-9]{1,8}$/i)?.[0]||(String(a.content_type||'').includes('json')?'.json':String(a.content_type||'').includes('html')?'.html':'.txt');
    const filename=`${String(i+1).padStart(2,'0')}-${safeName(artifactTitle(a))}${ext}`;
    records.push(entry(filename,new Uint8Array(await blob.arrayBuffer())));
    manifest.included.push({title:artifactTitle(a),filename,type:a.type,artifact_id:a.id,source_artifact_ids:a.source_artifact_ids});
  }
  if(!records.length)throw new Error('All results exceed the size limit for a package.');
  records.unshift(entry('README-MANIFEST.json',encoder.encode(JSON.stringify(manifest,null,2))));
  const url=URL.createObjectURL(makeZip(records));
  try {const link=document.createElement('a');link.href=url;link.download=`AEAI-investigation-${safeName(run.id)}.zip`;document.body.appendChild(link);link.click();link.remove();}
  finally {window.setTimeout(()=>URL.revokeObjectURL(url),30000);}
  return records.length-1;
}
