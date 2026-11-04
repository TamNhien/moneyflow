// PWA checks: no private data caching; opt-in OS notification without financial details.
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createContext, runInContext} from 'node:vm';
import assert from 'node:assert/strict';

const pwaSrc = readFileSync(resolve('frontend/pwa.js'),'utf8');
const swSrc = readFileSync(resolve('frontend/sw.js'),'utf8');
const memory = new Map();
const notifications = [];
const els = new Map();
let askCount=0;
let prompted=0;
const fakeReg = {showNotification:async(title,opt)=>{notifications.push({title,opt});}};
const mockNavigator = {
  standalone:false,
  serviceWorker:{register:async()=>fakeReg}
};
const Notification = {permission:'default',requestPermission:async()=>{askCount++;Notification.permission='granted';return 'granted';}};
const mockWindow = {
  isSecureContext:true, Notification,
  localStorage:{getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},
  addEventListener(){}, setInterval(){}, matchMedia:()=>({matches:false})
};
const ctx = createContext({
  window:mockWindow,navigator:mockNavigator,Notification,
  state:{user:{id:1,username:'tester'}},
  document:{visibilityState:'hidden',querySelector:(key)=>{
    if(!els.has(key))els.set(key,{textContent:'',hidden:false,disabled:false});return els.get(key);
  }},
  toast(){}, refreshReminders:async()=>{}, console,
  Date, Number, Promise
});
runInContext(pwaSrc,ctx,{filename:'pwa.js'});
await mockWindow.MoneyFlowPWA.onReminders(3,1);
assert.equal(notifications.length,0,'Disabled notifications must never fire');
await mockWindow.MoneyFlowPWA.handleAction('pwa-notify-on');
assert.equal(askCount,1,'Permission requested only after user action');
await mockWindow.MoneyFlowPWA.onReminders(3,1);
assert.equal(notifications.length,1);
assert.ok(!JSON.stringify(notifications).match(/giao dịch.*[0-9]|số dư|bí mật/i),'OS notification must not contain financial details');
await mockWindow.MoneyFlowPWA.onReminders(3,1);
assert.equal(notifications.length,1,'At most once per day');
ctx.document.visibilityState='visible';
memory.delete('moneyflow.notify.sent.u1');
await mockWindow.MoneyFlowPWA.onReminders(3,1);
assert.equal(notifications.length,1,'No notifications when app is visible');
ctx.document.visibilityState='hidden';
await mockWindow.MoneyFlowPWA.handleAction('pwa-notify-off');
await mockWindow.MoneyFlowPWA.onReminders(3,1);
assert.equal(notifications.length,1,'No notifications after disabling');
await mockWindow.MoneyFlowPWA.onReminders(3,2);
assert.equal(notifications.length,1,'No cross-user notifications');
console.log('PWA notification smoke PASS: explicit opt-in, privacy, per-user, per-day deduplication.');

const listeners = new Map();
const cached = new Map();
const cacheOps = [];
const fakeCache = {
 addAll:async assets=>{cacheOps.push(['addAll',assets]);for (const url of assets)cached.set(url,{ok:true,url});},
 match:async request=>cached.get(typeof request==='string'?request:request.url)??null,
 put:async(req,res)=>{cacheOps.push(['put',req.url]);cached.set(req.url,res)}
};
const caches = {open:async()=>fakeCache,keys:async()=>['moneyflow-shell-v1.0.24','moneyflow-shell-v1.0.25'],delete:async key=>{cacheOps.push(['delete',key]);return true;}};
const self={location:{origin:'https://127.0.0.1:8765'},clients:{claim:async()=>{},matchAll:async()=>[],openWindow:async()=>{}},skipWaiting:async()=>{},addEventListener:(name,fn)=>listeners.set(name,fn)};
const swctx=createContext({self,caches,URL,Response,Promise,Set,console,fetch:async req=>{const url=typeof req==='string'?req:req.url; if(url.includes('offline-nav'))throw Error('offline');return {ok:true,type:'basic',redirected:false,url,clone(){return this}};}});
runInContext(swSrc,swctx,{filename:'sw.js'});
assert.ok(listeners.has('fetch')&&listeners.has('install'),'Service worker registered');
let installWait;
listeners.get('install')({waitUntil:p=>installWait=p});
await installWait;
const cachedPaths = cacheOps[0][1];
assert.ok(cachedPaths.includes('/offline.html'));
assert.ok(cachedPaths.every(path => !/api\/?|reset|\/$|index\.html/.test(path)), 'Only public UI shell can be precached');
const request=(path,mode='cors',method='GET')=>{
 let handled=false;let response;
 const event={request:{url:'https://127.0.0.1:8765'+path,method,mode},respondWith:p=>{handled=true;response=p;}};
 listeners.get('fetch')(event);
 return {handled, response};
};
assert.equal(request('/api/dashboard').handled,false,'Never intercept financial APIs');
assert.equal(request('/api/login','cors','POST').handled,false,'Never intercept login POST');
assert.equal(request('/reset?token=secret','navigate').handled,false,'Never intercept password reset URLs');
assert.equal(request('/evil.txt').handled,false,'No arbitrary URL caching');
assert.equal(request('/app.js?token=private').handled,false,'No unknown query string caching');
assert.equal(request('/','navigate').handled,true,'Navigation uses network-first offline fallback');
console.log('Service worker smoke PASS: no financial API, password reset or navigation HTML caching.');
