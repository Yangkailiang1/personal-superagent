// 固定协议夹具：真实 Node 子进程，但不启动 Claude、不调用模型、不执行请求命令。
import {createInterface} from 'node:readline';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
const emit=x=>console.log(JSON.stringify({protocol:1,...x}));
createInterface({input:process.stdin}).on('line',line=>{
 const msg=JSON.parse(line);
 if(msg.action==='start') {
  mkdirSync(join(msg.cwd,'src'),{recursive:true});writeFileSync(join(msg.cwd,'src/result.txt'),'recorded output');
  emit({kind:'session',session_id:'recorded-http-session'});
  emit({kind:'permission',request_id:'permission-http',tool:'Bash',args:{command:'custom command'}});
 } else if(msg.action==='respond') {
  emit({kind:'permission_applied',request_id:msg.request_id,decision:msg.decision});
  emit({kind:'result',state:'succeeded',text:'fixture delivered',session_id:'recorded-http-session'});
  process.stdin.pause();process.exitCode=0;
 }
});
