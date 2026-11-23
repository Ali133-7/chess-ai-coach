const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),dir=path.join(root,'tests','ui');
for(const file of fs.readdirSync(dir).filter(x=>x.endsWith('.cjs')).sort()){
 const r=spawnSync(process.execPath,[path.join(dir,file)],{cwd:root,stdio:'inherit',env:{...process.env,RUNTIME:root}});
 if(r.status!==0)process.exit(r.status||1);
}
