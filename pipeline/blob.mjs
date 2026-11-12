import{put,get}from'@vercel/blob';import{readFile,writeFile,mkdir}from'node:fs/promises';import{dirname}from'node:path';
const [,,action,...args]=process.argv;const pub=process.env.BLOB_READ_WRITE_TOKEN,priv=process.env.PRIVATE_READ_WRITE_TOKEN;
if(!pub||!priv)throw new Error('Both Blob tokens are required');
async function download(path,file,token,access){const blob=await get(path,{access,token});if(!blob)return false;await mkdir(dirname(file),{recursive:true});await writeFile(file,Buffer.from(await new Response(blob.stream).arrayBuffer()));return true}
if(action==='pull'){for(const [remote,local] of [['private/bdl_nba.sqlite','bdl_nba.sqlite'],['private/minutes_model.pkl','minutes_model.pkl']])await download(remote,local,priv,'private')}
else if(action==='pull-history'){await download('results/history.json','publish/results/history.json',pub,'public');if(args[0])await download(`slates/${args[0]}/predictions.json`,`publish/slates/${args[0]}/predictions.json`,pub,'public')}
else if(action==='push-private'){for(const file of args)await put(`private/${file}`,await readFile(file),{access:'private',allowOverwrite:true,addRandomSuffix:false,token:priv});}
else if(action==='push-public'){for(const file of args)await put(file.replace(/^publish\//,''),await readFile(file),{access:'public',allowOverwrite:true,addRandomSuffix:false,token:pub,contentType:'application/json'});}
else throw new Error('Unknown action');
