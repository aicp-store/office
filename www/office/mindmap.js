const project = window.location.pathname.split('/')[1];
const API_GEN = `/api/applications/${project}/generate`;
const params = new URLSearchParams(window.location.search);
const roomId = params.get('room') || 'default';

let canvas, ctx, w, h;
let offsetX = 0, offsetY = 0, scale = 1;
let nodes = {}, rootId = null, currentNode = null;
let showChildren = new Set();
let expandAnim = null, collapseAnim = null;
let bgImage = null;
let isAIGenerating = false;
let isPresentation = false;
let savedState = null;
let myWsId = null;
let ws = null;
let onlineCount = 1;

let settings = { bgColor: '#fafafa', bgOpacity: 0.10, nodeColor: '#ffffff', textColor: '#333333', focusColor: '#6366f1', focusTextColor: '#ffffff', lineColor: '#6366f1', fontFamily: 'system-ui', fontSize: 12, lineSpeed: 1, flipSpeed: 1, staggerDelay: 1 };
const defaultSettings = { ...settings };
const LEVEL_GAP = 220, SIBLING_GAP = 26, START_X = 50, PAD = 12, MIN_W = 70, MAX_W = 180, NODE_H = 40;

function easeOutQuad(t) { return 1 - (1-t)*(1-t); }
function easeInOutCubic(t) { return t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2; }
function easeOutBack(t) { const c1 = 1.70158; return 1 + (c1+1) * Math.pow(t-1, 3) + c1 * Math.pow(t-1, 2); }
function easeInQuad(t) { return t*t; }

function measureSize(text) { const font = `${settings.fontSize}px "${settings.fontFamily}"`; ctx.font = font; let lines = [], cur = '', maxW = 0; for (let ch of text) { let test = cur + ch; if (ctx.measureText(test).width > MAX_W - PAD*2 && cur.length) { lines.push(cur); maxW = Math.max(maxW, ctx.measureText(cur).width); cur = ch; } else cur = test; } if (cur) { lines.push(cur); maxW = Math.max(maxW, ctx.measureText(cur).width); } return { w: Math.max(MIN_W, maxW + PAD*2 + 20), h: Math.max(NODE_H, lines.length * (settings.fontSize + 6) + PAD), lines }; }

function getVisible() { if (isPresentation) { let vis = new Set(); for (let id in nodes) vis.add(id); return vis; } let vis = new Set(); if (!currentNode) return vis; let p = currentNode; while (p) { vis.add(p.id); p = p.parentId ? nodes[p.parentId] : null; } let path = []; p = currentNode; while (p) { path.unshift(p); p = p.parentId ? nodes[p.parentId] : null; } for (let node of path) { if (node.parentId && showChildren.has(node.parentId)) for (let cid of nodes[node.parentId].children) vis.add(cid); } if (currentNode && showChildren.has(currentNode.id)) for (let cid of currentNode.children) vis.add(cid); if (expandAnim) { let ap = nodes[expandAnim.parentId]; if (ap) for (let cid of ap.children) vis.add(cid); } if (collapseAnim) for (let cid of collapseAnim.childIds) vis.add(cid); return vis; }

function treeToMarkdown() { function w(nid,d){ let n=nodes[nid],p='#'.repeat(Math.min(d+1,6)),md=`${p} ${n.text}\n\n`; for(let c of n.children) md+=w(c,d+1); return md; } return w(rootId,0); }

function layoutTree(tempExpandId) { if (!rootId) return; if (isPresentation) { layoutPresentation(); return; } function layout(node, x, y) { let sz = measureSize(node.text); node.w = sz.w; node.h = sz.h; node.lines = sz.lines; node.x = x; node.y = y; let expanded = showChildren.has(node.id) || node.id === tempExpandId; if (!expanded || !node.children || node.children.length === 0) return; let totalH = 0; for (let cid of node.children) { let child = nodes[cid]; if (!child) continue; if (!child.h) { let sz = measureSize(child.text); child.w = sz.w; child.h = sz.h; child.lines = sz.lines; } totalH += child.h; } totalH += (node.children.length - 1) * SIBLING_GAP; let startY = y + node.h/2 - totalH/2; for (let cid of node.children) { let child = nodes[cid]; layout(child, x + node.w + LEVEL_GAP, startY); startY += child.h + SIBLING_GAP; } } layout(nodes[rootId], START_X, h/2 - 30); }

function layoutPresentation() { let minGap = 14, minLevelGap = 160; function calcHeight(node) { if (!node.children || node.children.length === 0 || !showChildren.has(node.id)) { if (!node.h) { let sz = measureSize(node.text); node.w = sz.w; node.h = sz.h; node.lines = sz.lines; } return node.h; } let total = 0; for (let cid of node.children) { let c = nodes[cid]; if (c) total += calcHeight(c); } total += (node.children.length - 1) * minGap; if (!node.h) { let sz = measureSize(node.text); node.w = sz.w; node.h = sz.h; node.lines = sz.lines; } return Math.max(node.h, total); } function layout(node, x, y, gap) { let sz = measureSize(node.text); node.w = sz.w; node.h = sz.h; node.lines = sz.lines; node.x = x; node.y = y; if (!node.children || node.children.length === 0 || !showChildren.has(node.id)) return; let childYs = [], totalH = 0; for (let cid of node.children) { let c = nodes[cid]; if (!c) continue; totalH += calcHeight(c); } totalH += (node.children.length - 1) * gap; let startY = y + node.h/2 - totalH/2; for (let cid of node.children) { let c = nodes[cid]; if (!c) continue; let ch = calcHeight(c); childYs.push({ id: cid, y: startY + ch/2, h: ch }); startY += ch + gap; } for (let i = 1; i < childYs.length; i++) { let prev = childYs[i-1], curr = childYs[i]; if ((curr.y - curr.h/2) - (prev.y + prev.h/2) < 4) { let adjust = ((prev.y + prev.h/2) + 4 - (curr.y - curr.h/2)) / 2; childYs[i-1].y -= adjust; childYs[i].y += adjust; } } for (let cy of childYs) { let child = nodes[cy.id]; layout(child, x + node.w + minLevelGap, cy.y, gap); } } calcHeight(nodes[rootId]); layout(nodes[rootId], START_X, h/2 - 30, minGap); }

function hexToRgba(hex, alpha) { let r = parseInt(hex.slice(1,3), 16), g = parseInt(hex.slice(3,5), 16), b = parseInt(hex.slice(5,7), 16); return `rgba(${r},${g},${b},${alpha})`; }

function getChildPorts(parentNode) { let children = parentNode.children; if (children.length === 0) return []; let ports = []; for (let i = 0; i < children.length; i++) ports.push({ childId: children[i], portY: parentNode.y + (parentNode.h / (children.length + 1)) * (i + 1) }); return ports; }

function draw() { if (!ctx) return; ctx.clearRect(0, 0, w, h); ctx.fillStyle = settings.bgColor; ctx.fillRect(0, 0, w, h); if (bgImage && settings.bgOpacity > 0) { ctx.globalAlpha = settings.bgOpacity; let ir = bgImage.width/bgImage.height, cr = w/h, sw, sh, sx, sy; if (ir > cr) { sh = h; sw = h*ir; sx = (w-sw)/2; sy = 0; } else { sw = w; sh = w/ir; sx = 0; sy = (h-sh)/2; } ctx.drawImage(bgImage, sx, sy, sw, sh); ctx.globalAlpha = 1; } ctx.save(); ctx.translate(offsetX, offsetY); ctx.scale(scale, scale); let vis = getVisible(); ctx.lineWidth = 2/scale; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; for (let id in nodes) { let node = nodes[id]; if (!vis.has(id)) continue; let ports = getChildPorts(node); for (let port of ports) { let child = nodes[port.childId]; if (!vis.has(port.childId)) continue; let fromX = node.x + node.w, fromY = port.portY, toX = child.x, toY = child.y + child.h/2, midX = fromX + (toX - fromX) * 0.5; let lineProg = 1; if (expandAnim?.childStates?.[port.childId]) lineProg = expandAnim.childStates[port.childId].lineProgress; let dissolveAlpha = 1; if (collapseAnim?.childIds.includes(port.childId)) dissolveAlpha = collapseAnim.progress; if (lineProg <= 0 || dissolveAlpha <= 0) continue; let lc = settings.lineColor; ctx.strokeStyle = `rgba(${parseInt(lc.slice(1,3),16)},${parseInt(lc.slice(3,5),16)},${parseInt(lc.slice(5,7),16)},${(0.4 + lineProg * 0.4) * dissolveAlpha})`; if (lineProg < 1) { let s1 = Math.min(1, lineProg/0.35), s2 = Math.min(1, Math.max(0, (lineProg-0.35)/0.35)), s3 = Math.min(1, Math.max(0, (lineProg-0.7)/0.3)); ctx.beginPath(); ctx.moveTo(fromX, fromY); ctx.lineTo(fromX + (midX-fromX)*easeOutQuad(s1), fromY); if (s2>0) ctx.lineTo(midX, fromY + (toY-fromY)*easeInOutCubic(s2)); if (s3>0) ctx.lineTo(midX + (toX-midX)*easeOutQuad(s3), toY); ctx.stroke(); } else { ctx.beginPath(); ctx.moveTo(fromX, fromY); ctx.lineTo(midX, fromY); ctx.lineTo(midX, toY); ctx.lineTo(toX, toY); ctx.stroke(); } } } const font = `${settings.fontSize}px "${settings.fontFamily}"`; for (let id in nodes) { let node = nodes[id]; if (!vis.has(id)) continue; let flipProg = 1, isExpandChild = false, dissolveProg = 1; if (expandAnim?.childStates?.[id]) { isExpandChild = true; flipProg = expandAnim.childStates[id].flipProgress; if (flipProg <= 0) continue; } if (collapseAnim?.childIds.includes(id)) dissolveProg = collapseAnim.progress; if (dissolveProg <= 0) continue; let isFocus = !isPresentation && currentNode && currentNode.id === id; let alpha = dissolveProg; if (isExpandChild && flipProg < 1) alpha = Math.min(1, flipProg * 1.5) * dissolveProg; if (alpha <= 0) continue; ctx.globalAlpha = alpha; ctx.save(); if (isExpandChild && flipProg < 1 && dissolveProg >= 1) { let cx = node.x + node.w/2, cy = node.y + node.h/2; ctx.translate(cx, cy); let scaleY; if (flipProg < 0.6) { scaleY = easeOutQuad(flipProg/0.6) * 0.9; } else { scaleY = 0.9 + 0.1 * easeOutBack((flipProg-0.6)/0.4); } ctx.scale(1, scaleY); ctx.translate(-cx, -cy); } ctx.fillStyle = isFocus ? hexToRgba(settings.focusColor, 0.9) : settings.nodeColor; ctx.beginPath(); ctx.roundRect(node.x, node.y, node.w, node.h, 6); ctx.fill(); ctx.strokeStyle = isFocus ? settings.focusColor : '#ddd'; ctx.lineWidth = 1/scale; ctx.beginPath(); ctx.roundRect(node.x, node.y, node.w, node.h, 6); ctx.stroke(); ctx.fillStyle = isFocus ? settings.focusTextColor : settings.textColor; ctx.font = font; let lines = node.lines || [node.text], lineH = settings.fontSize + 6, startY = node.y + (node.h - lines.length*lineH)/2 + lineH - 3; for (let i=0; i<lines.length; i++) ctx.fillText(lines[i], node.x+PAD, startY + i*lineH); ctx.restore(); ctx.globalAlpha = 1; } ctx.fillStyle = 'rgba(0,0,0,0.05)'; ctx.font = `bold 26px "${settings.fontFamily}"`; ctx.fillText('AICP-Mind', w/scale - 190, h/scale - 24); if (bgImage) { ctx.globalAlpha = 0.15; ctx.drawImage(bgImage, w/scale - 80, h/scale - 70, 60, 60); ctx.globalAlpha = 1; } ctx.restore(); }

function animateCamera(node) { if(!node||isPresentation)return; let tx=w/2-(node.x+node.w/2),ty=h/2-(node.y+node.h/2),startX=offsetX,startY=offsetY,start=null; function step(ts){if(!start)start=ts;let t=Math.min(1,(ts-start)/400),e=1-Math.pow(1-t,3);offsetX=startX+(tx-startX)*e;offsetY=startY+(ty-startY)*e;scale=1;draw();if(t<1)requestAnimationFrame(step);else{offsetX=tx;offsetY=ty;draw();}} requestAnimationFrame(step); }

function startExpandAnimation(parentNode) { return new Promise(resolve => { showChildren.add(parentNode.id); let children = parentNode.children.map(cid => nodes[cid]).filter(Boolean); if (children.length === 0) { layoutTree(parentNode.id); draw(); resolve(); return; } layoutTree(parentNode.id); let childStates = {}; children.forEach(child => { childStates[child.id] = { lineProgress:0, flipProgress:0, lineStart:0, flipStart:0, lineDone:false }; }); let startTime = performance.now(); let lineDuration = 500/settings.lineSpeed, flipDuration = 500/settings.flipSpeed, staggerDelay = 400/settings.staggerDelay, gapBetweenLineAndFlip = 50; children.forEach((child, index) => { childStates[child.id].lineStart = index * staggerDelay; childStates[child.id].flipStart = childStates[child.id].lineStart + lineDuration + gapBetweenLineAndFlip; }); expandAnim = { parentId: parentNode.id, childStates: childStates, startTime: startTime }; draw(); function step(now) { let elapsed = now - startTime; let allDone = true; children.forEach(child => { let cs = childStates[child.id]; if (elapsed >= cs.lineStart && !cs.lineDone) { let le = elapsed - cs.lineStart; cs.lineProgress = le < lineDuration ? easeOutQuad(le / lineDuration) : (cs.lineDone = true, 1); } if (cs.lineDone && elapsed >= cs.flipStart && cs.flipProgress < 1) { let fe = elapsed - cs.flipStart; cs.flipProgress = fe < flipDuration ? fe / flipDuration : 1; } if (cs.flipProgress < 1) allDone = false; }); draw(); if (allDone) { expandAnim = null; layoutTree(parentNode.id); draw(); resolve(); } else requestAnimationFrame(step); } requestAnimationFrame(step); }); }

function startCollapseAnimation(parentNode) { return new Promise(resolve => { let childIds = parentNode.children.slice(); if (childIds.length === 0) { showChildren.delete(parentNode.id); layoutTree(); draw(); resolve(); return; } let dissolveDuration = 250; collapseAnim = { childIds: childIds, progress: 1, startTime: performance.now() }; draw(); function step(now) { let raw = Math.min(1, (now-collapseAnim.startTime)/dissolveDuration); collapseAnim.progress = 1 - easeInQuad(raw); draw(); if (raw >= 1) { collapseAnim = null; showChildren.delete(parentNode.id); layoutTree(); draw(); resolve(); } else requestAnimationFrame(step); } requestAnimationFrame(step); }); }

function isLastUnexpanded(node) { return node && node.children.length > 0 && !showChildren.has(node.id) && currentNode && currentNode.id === node.id; }
async function expandAndEnter(node) { if(!node||node.children.length===0)return; if(showChildren.has(node.id)){currentNode=nodes[node.children[0]];layoutTree();draw();animateCamera(currentNode);return;} await startExpandAnimation(node); currentNode=nodes[node.children[0]];layoutTree();draw();animateCamera(currentNode); }
async function collapseCurrent() { if(!currentNode)return; if(showChildren.has(currentNode.id)){await startCollapseAnimation(currentNode);} else if(currentNode.parentId){currentNode=nodes[currentNode.parentId];layoutTree();draw();animateCamera(currentNode);} }
function moveUp(){if(!currentNode||isPresentation)return;if(showChildren.has(currentNode.id)){collapseCurrent();return;}if(!currentNode.parentId)return;let p=nodes[currentNode.parentId];if(!showChildren.has(p.id))return;let s=p.children.map(id=>nodes[id]),i=s.findIndex(n=>n.id===currentNode.id);if(i===-1)return;let t=i>0?s[i-1]:s[s.length-1];currentNode=t;layoutTree();draw();animateCamera(t);}
function moveDown(){if(!currentNode||isPresentation)return;if(showChildren.has(currentNode.id)){collapseCurrent();return;}if(!currentNode.parentId)return;let p=nodes[currentNode.parentId];if(!showChildren.has(p.id))return;let s=p.children.map(id=>nodes[id]),i=s.findIndex(n=>n.id===currentNode.id);if(i===-1)return;let t=i<s.length-1?s[i+1]:s[0];currentNode=t;layoutTree();draw();animateCamera(t);}
function clickSelect(node){if(!node||isPresentation)return;if(currentNode&&currentNode.id===node.id)return;currentNode=node;layoutTree();draw();animateCamera(node);updateStatus();}
function doubleClick(node){if(!node||isPresentation)return;if(isLastUnexpanded(node)){expandAndEnter(node);}else{clickSelect(node);}}

let ctxMenu=document.getElementById('ctxMenu');
function showContextMenu(e,node){ if(!currentNode||!node||node.id!==currentNode.id||isPresentation)return; e.preventDefault(); document.getElementById('ctxExpand').style.display=isLastUnexpanded(node)?'block':'none'; ctxMenu.style.display='flex'; ctxMenu.style.left=e.clientX+'px';ctxMenu.style.top=e.clientY+'px'; let r=ctxMenu.getBoundingClientRect(); if(r.right>innerWidth)ctxMenu.style.left=(e.clientX-r.width)+'px'; if(r.bottom>innerHeight)ctxMenu.style.top=(e.clientY-r.height)+'px'; }
function hideContextMenu(){ctxMenu.style.display='none';}

function addChild(){
    if(!currentNode||isPresentation)return;
    let pid=currentNode.id;
    let nid=`n_${Date.now()}_${Math.random()}`,sz=measureSize("新节点");
    nodes[nid]={id:nid,text:"新节点",parentId:pid,children:[],w:sz.w,h:sz.h,lines:sz.lines};
    nodes[pid].children.push(nid);
    if(!showChildren.has(pid))showChildren.add(pid);
    layoutTree();draw();
    currentNode=nodes[nid];
    animateCamera(currentNode);
    broadcastAction('node_add',{nodeId:nid,parentId:pid,text:'新节点'});
}
function editNode(){if(!currentNode||isPresentation)return;document.getElementById('editInput').value=currentNode.text;document.getElementById('overlay').style.display='block';document.getElementById('editModal').style.display='flex';document.getElementById('editInput').focus();}
function saveEdit(){
    let t=document.getElementById('editInput').value.trim();
    if(t&&currentNode){
        currentNode.text=t;let sz=measureSize(t);
        currentNode.w=sz.w;currentNode.h=sz.h;currentNode.lines=sz.lines;
        layoutTree();draw();
        broadcastAction('node_edit',{nodeId:currentNode.id,text:t});
    }
    document.getElementById('overlay').style.display='none';document.getElementById('editModal').style.display='none';
}
function deleteNode(){
    if(!currentNode||currentNode.id===rootId||isPresentation)return;
    let p=nodes[currentNode.parentId];
    if(p){
        let did=currentNode.id,pid=p.id;
        function rm(nid){let n=nodes[nid];if(n){for(let c of n.children)rm(c);delete nodes[nid];}}
        rm(did);
        p.children=p.children.filter(c=>c!==did);
        if(showChildren.has(did))showChildren.delete(did);
        currentNode=p;layoutTree();draw();animateCamera(currentNode);
        broadcastAction('node_delete',{nodeId:did,parentId:pid});
    }
}

function buildTree(data,pid=null){let id=`n_${Date.now()}_${Math.random()}`;nodes[id]={id,text:data.text,parentId:pid,children:[]};for(let c of(data.children||[]))nodes[id].children.push(buildTree(c,id));return id;}
function getAncestorPath(node){let path=[],p=node;while(p){path.unshift(p.text);p=p.parentId?nodes[p.parentId]:null;}return path.join(" → ");}

async function aiExpandNode(node){
    if(!node||isAIGenerating)return;
    if(node.children.length>0){if(!confirm(`确定要用 AI 重新生成「${node.text}」的子节点吗？`))return;}
    isAIGenerating=true;
    let prompt=`主题：「${node.text}」\n上下文：${getAncestorPath(node)}\n请为「${node.text}」生成 3-5 个直接子节点。每个子节点简洁（10字以内）。语言和「${node.text}」保持一致。`;
    try{
        let res=await fetch(API_GEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'generate',text:prompt})});
        let data=await res.json();if(data.error)throw new Error(data.error);
        let oldChildren=node.children.slice();for(let cid of oldChildren)deleteNodeRecursive(cid);
        node.children=[];for(let child of(data.tree.children||[]))node.children.push(buildTree(child,node.id));
        showChildren.add(node.id);layoutTree();draw();animateCamera(node);
        broadcastAction('ai_expand',{nodeId:node.id});
    }catch(e){alert('生成失败: '+e.message);}
    isAIGenerating=false;
}
function deleteNodeRecursive(nid){let n=nodes[nid];if(n){for(let cid of n.children)deleteNodeRecursive(cid);if(showChildren.has(nid))showChildren.delete(nid);delete nodes[nid];}}

function exportJSON(){function s(nid){let n=nodes[nid];return{text:n.text,children:n.children.map(s)};}navigator.clipboard.writeText(JSON.stringify(s(rootId),null,2)).then(()=>alert('已复制 JSON'));}
function importJSON(jsonStr){
    try{
        let data=JSON.parse(jsonStr);
        if(data.rootId && data.nodes){
            nodes={};showChildren.clear();
            for(let id in data.nodes){
                let n=data.nodes[id];
                nodes[id]={id:n.id,text:n.text,parentId:n.parentId,children:[...n.children],w:n.w,h:n.h,lines:n.lines};
            }
            rootId=data.rootId;currentNode=nodes[rootId];
        }else if(data.text && data.children){
            nodes={};showChildren.clear();
            function b(data,pid){let id=`n_${Date.now()}_${Math.random()}`;nodes[id]={id,text:data.text,parentId:pid,children:[]};for(let c of(data.children||[]))nodes[id].children.push(b(c,id));return id;}
            rootId=b(data,null);currentNode=nodes[rootId];
        }
        layoutTree();draw();if(currentNode)animateCamera(currentNode);
    }catch(e){alert('JSON 格式错误');}
}

async function aiGenerate(){
    let t=document.getElementById('aiPrompt').value;if(!t.trim())return;
    try{
        let res=await fetch(API_GEN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'generate',text:t})});
        let data=await res.json();if(data.error)throw new Error(data.error);
        nodes={};showChildren.clear();rootId=buildTree(data.tree);currentNode=nodes[rootId];
        requestAnimationFrame(()=>{requestAnimationFrame(()=>{layoutTree();offsetX=w/2-(currentNode.x+currentNode.w/2);offsetY=h/2-(currentNode.y+currentNode.h/2);scale=1;draw();updateStatus();});});
    }catch(e){alert('生成失败: '+e.message);}
}

function enterPresentation() { savedState = { showChildren: new Set(showChildren), currentNode: currentNode, offsetX, offsetY, scale }; isPresentation = true; showChildren.clear(); function expandAll(nid) { let n = nodes[nid]; if (!n) return; showChildren.add(nid); for (let cid of n.children) expandAll(cid); } expandAll(rootId); layoutPresentation(); draw(); document.getElementById('btnExpandAll').classList.add('active'); updateStatus(); }
function exitPresentation() { if (savedState) { showChildren = savedState.showChildren; currentNode = savedState.currentNode; offsetX = savedState.offsetX; offsetY = savedState.offsetY; scale = savedState.scale; savedState = null; } isPresentation = false; layoutTree(); draw(); if (currentNode) animateCamera(currentNode); document.getElementById('btnExpandAll').classList.remove('active'); updateStatus(); }
function togglePresentation() { isPresentation ? exitPresentation() : enterPresentation(); }
function exportPNG() { let link = document.createElement('a'); link.download = 'aicp-mind.png'; link.href = canvas.toDataURL(); link.click(); }

function initDemo(){
    let demo={text:"AICP 协议",children:[{text:"核心思想",children:[{text:"信封即状态"},{text:"AI 无状态"},{text:"路由即接口"}]},{text:"技术组件",children:[{text:"热重载"},{text:"Saver 插件"}]},{text:"应用场景",children:[{text:"思维导图"},{text:"文本转换"}]}]};
    nodes={};showChildren.clear();rootId=buildTree(demo);currentNode=nodes[rootId];
    requestAnimationFrame(()=>{requestAnimationFrame(()=>{layoutTree();if(currentNode){offsetX=w/2-(currentNode.x+currentNode.w/2);offsetY=h/2-(currentNode.y+currentNode.h/2);}scale=1;draw();updateStatus();});});
}

function updateStatus(){document.getElementById('status').innerHTML=`${currentNode&&currentNode.text||'就绪'} 👥${onlineCount}`;}
function updateSettingsUI(){ document.getElementById('bgColor').value=settings.bgColor;document.getElementById('nodeColor').value=settings.nodeColor;document.getElementById('textColor').value=settings.textColor;document.getElementById('focusColor').value=settings.focusColor;document.getElementById('focusTextColor').value=settings.focusTextColor;document.getElementById('lineColor').value=settings.lineColor;document.getElementById('fontFamily').value=settings.fontFamily;document.getElementById('fontSize').value=settings.fontSize;document.getElementById('bgOpacity').value=settings.bgOpacity*100; }
function closeAllPanels(){ document.querySelectorAll('.float-panel').forEach(p=>p.classList.remove('open')); }

function initCanvas(){
    canvas=document.getElementById('canvas');ctx=canvas.getContext('2d');
    function resize(){w=innerWidth;h=innerHeight;canvas.width=w;canvas.height=h;layoutTree();draw();}
    window.addEventListener('resize',resize);resize();
    let drag=false,sx,sy,sox,soy,lastClickTime=0,lastClickNode=null;
    canvas.addEventListener('mousedown',e=>{closeAllPanels();let node=hitTest(e.clientX,e.clientY);if(e.button===2){if(node)showContextMenu(e,node);return;}if(e.button===0){let now=Date.now();if(node&&lastClickNode&&lastClickNode.id===node.id&&(now-lastClickTime)<350){doubleClick(node);lastClickTime=0;lastClickNode=null;return;}lastClickTime=now;lastClickNode=node;if(node)clickSelect(node);drag=true;sx=e.clientX;sy=e.clientY;sox=offsetX;soy=offsetY;canvas.style.cursor='grabbing';}});
    window.addEventListener('mousemove',e=>{if(!drag)return;offsetX=sox+(e.clientX-sx);offsetY=soy+(e.clientY-sy);draw();});
    window.addEventListener('mouseup',()=>{drag=false;canvas.style.cursor='pointer';});
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    if(!CanvasRenderingContext2D.prototype.roundRect){CanvasRenderingContext2D.prototype.roundRect=function(x,y,w,h,r){if(w<2*r)r=w/2;if(h<2*r)r=h/2;this.moveTo(x+r,y);this.lineTo(x+w-r,y);this.quadraticCurveTo(x+w,y,x+w,y+r);this.lineTo(x+w,y+h-r);this.quadraticCurveTo(x+w,y+h,x+w-r,y+h);this.lineTo(x+r,y+h);this.quadraticCurveTo(x,y+h,x,y+h-r);this.lineTo(x,y+r);this.quadraticCurveTo(x,y,x+r,y);return this;};}
}
function hitTest(sx,sy){let wx=(sx-offsetX)/scale,wy=(sy-offsetY)/scale,vis=getVisible(),all=[];for(let id in nodes)if(vis.has(id))all.push(nodes[id]);for(let n of all)if(wx>=n.x&&wx<=n.x+n.w&&wy>=n.y&&wy<=n.y+n.h)return n;return null;}

// ═══ 协同 WebSocket ═══
function connectCollaboration() {
    const wsPort = (window.location.port || 9000) * 1 + 1;
    const WS_URL = `ws://${window.location.hostname}:${wsPort}/ws?channel=room_${roomId}`;
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        ws.send(JSON.stringify({
            type: 'envelop',
            receiver: 'builtins/system/broadcast',
            payload: { action: 'join', room_id: roomId, name: 'User' }
        }));
    };

    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'connected') { myWsId = data.ws_id; return; }
        
        if (data.type === 'envelop_result' && data.payload) {
            if (data.payload.members) {
                onlineCount = data.payload.members.length;
                updateStatus();
            }
            if (data.payload.state && data.payload.state.rootId && data.payload.state.nodes) {
                importJSON(JSON.stringify(data.payload.state));
            }
            return;
        }
        
        if (data.type === 'member_joined') { onlineCount = data.total; updateStatus(); return; }
        if (data.type === 'member_left') { onlineCount = data.total; updateStatus(); return; }
        
        if (data.type === 'sync' && data.sender_ws_id !== myWsId) {
            executeRemoteAction(data.action, data.payload);
        }
    };

    ws.onclose = () => { setTimeout(connectCollaboration, 2000); };
    ws.onerror = () => {};

    window.addEventListener('beforeunload', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'envelop',
                receiver: 'builtins/system/broadcast',
                payload: { action: 'leave', room_id: roomId }
            }));
        }
    });
}

function broadcastAction(actionType, payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
        type: 'envelop',
        receiver: 'builtins/system/broadcast',
        payload: { action: 'broadcast', room_id: roomId, data: { action: actionType, payload } }
    }));
}

function executeRemoteAction(action, payload) {
    switch (action) {
        case 'node_add': addNodeRemote(payload); break;
        case 'node_edit': editNodeRemote(payload); break;
        case 'node_delete': deleteNodeRemote(payload); break;
        case 'ai_expand': aiExpandNodeRemote(payload); break;
    }
}

function addNodeRemote(data) {
    if (!nodes[data.parentId]) return;
    nodes[data.nodeId] = { id: data.nodeId, text: data.text, parentId: data.parentId, children: [], w: 70, h: 40, lines: [data.text] };
    nodes[data.parentId].children.push(data.nodeId);
    if (!showChildren.has(data.parentId)) showChildren.add(data.parentId);
    layoutTree(); draw();
}

function editNodeRemote(data) {
    if (!nodes[data.nodeId]) return;
    nodes[data.nodeId].text = data.text;
    let sz = measureSize(data.text);
    nodes[data.nodeId].w = sz.w; nodes[data.nodeId].h = sz.h; nodes[data.nodeId].lines = sz.lines;
    layoutTree(); draw();
}

function deleteNodeRemote(data) {
    if (!nodes[data.nodeId] || !nodes[data.parentId]) return;
    deleteNodeRecursive(data.nodeId);
    nodes[data.parentId].children = nodes[data.parentId].children.filter(c => c !== data.nodeId);
    layoutTree(); draw();
}

function aiExpandNodeRemote(data) {
    if (!nodes[data.nodeId]) return;
    showChildren.add(data.nodeId);
    layoutTree(); draw();
}

// ═══ 绑定事件 ═══
function bindAll(){
    document.getElementById('btnAi').onclick=()=>{document.getElementById('aiPanel').classList.toggle('open');};
    document.getElementById('aiGenerateBtn').onclick=()=>{aiGenerate();closeAllPanels();};
    document.getElementById('btnImport').onclick=()=>{document.getElementById('overlay').style.display='block';document.getElementById('importModal').style.display='flex';};
    document.getElementById('btnEdit').onclick=editNode;document.getElementById('btnAdd').onclick=addChild;document.getElementById('btnDelete').onclick=deleteNode;
    document.getElementById('btnExpandAll').onclick=togglePresentation;
    document.getElementById('btnCollapseAll').onclick=()=>{if(isPresentation)exitPresentation();};
    document.getElementById('btnExportPNG').onclick=exportPNG;
    document.getElementById('btnExportMD').onclick=()=>{const md=treeToMarkdown();const p=window.location.pathname.split('/')[1];window.open(`/${p}/text-processor.html?content=`+encodeURIComponent(md),'_blank');};
    document.getElementById('btnExportJSON').onclick=exportJSON;
    document.getElementById('btnSettings').onclick=()=>{document.getElementById('settingsPanel').classList.toggle('open');};
    document.getElementById('saveBtn').onclick=saveEdit;
    document.getElementById('cancelBtn').onclick=()=>{document.getElementById('overlay').style.display='none';document.getElementById('editModal').style.display='none';};
    document.getElementById('importSaveBtn').onclick=()=>{importJSON(document.getElementById('importInput').value);document.getElementById('overlay').style.display='none';document.getElementById('importModal').style.display='none';};
    document.getElementById('importCancelBtn').onclick=()=>{document.getElementById('overlay').style.display='none';document.getElementById('importModal').style.display='none';};
    document.getElementById('ctxExpand').onclick=()=>{hideContextMenu();if(currentNode)expandAndEnter(currentNode);};
    document.getElementById('ctxAI').onclick=()=>{hideContextMenu();if(currentNode)aiExpandNode(currentNode);};
    document.getElementById('ctxEdit').onclick=()=>{hideContextMenu();editNode();};
    document.getElementById('ctxAddChild').onclick=()=>{hideContextMenu();addChild();};
    document.getElementById('ctxDelete').onclick=()=>{hideContextMenu();deleteNode();};
    document.addEventListener('click',(e)=>{if(!e.target.closest('.float-panel')&&!e.target.closest('.toolbar button'))closeAllPanels();hideContextMenu();});
    document.getElementById('bgImageBtn').onclick=()=>document.getElementById('bgImageInput').click();
    document.getElementById('bgImageClear').onclick=()=>{bgImage=null;draw();};
    document.getElementById('bgImageInput').onchange=e=>{let f=e.target.files[0];if(f){let r=new FileReader();r.onload=ev=>{let i=new Image();i.onload=()=>{bgImage=i;draw();};i.src=ev.target.result;};r.readAsDataURL(f);}};
    document.getElementById('bgOpacity').oninput=e=>{settings.bgOpacity=e.target.value/100;draw();};
    ['bgColor','nodeColor','textColor','focusColor','focusTextColor','lineColor'].forEach(id=>{document.getElementById(id).oninput=e=>{settings[id]=e.target.value;draw();};});
    document.getElementById('fontFamily').onchange=e=>{settings.fontFamily=e.target.value;layoutTree();draw();};
    document.getElementById('fontSize').onchange=e=>{settings.fontSize=parseInt(e.target.value);layoutTree();draw();};
    document.getElementById('resetSettingsBtn').onclick=()=>{settings={...defaultSettings};bgImage=null;updateSettingsUI();layoutTree();draw();};
    window.addEventListener('keydown',e=>{if(document.getElementById('editModal').style.display==='flex'||document.getElementById('importModal').style.display==='flex')return;if(e.key==='Escape'){if(isPresentation)exitPresentation();else closeAllPanels();}else if(e.ctrlKey&&e.key==='e'){e.preventDefault();enterPresentation();}else if(e.ctrlKey&&e.key==='w'){e.preventDefault();exitPresentation();}else if(e.key==='ArrowRight'){if(currentNode&&currentNode.children.length)expandAndEnter(currentNode);e.preventDefault();}else if(e.key==='ArrowLeft'){collapseCurrent();e.preventDefault();}else if(e.key==='ArrowUp'){moveUp();e.preventDefault();}else if(e.key==='ArrowDown'){moveDown();e.preventDefault();}else if(e.key==='Delete'){deleteNode();e.preventDefault();}});
}

// 在 initDemo() 函数定义之前加
function tryImportFromURL() {
    const params = new URLSearchParams(window.location.search);
    const importData = params.get('import');
    if (importData) {
        try {
            const decoded = decodeURIComponent(importData);
            importJSON(decoded);
            return true;
        } catch(e) {
            console.warn('URL import failed:', e);
        }
    }
    return false;
}

// 修改 start() 函数
async function start() {
    initCanvas();
    bindAll();
    
    if (!tryImportFromURL()) {
        initDemo();
    }
    
    updateSettingsUI();
    connectCollaboration();
}
start();