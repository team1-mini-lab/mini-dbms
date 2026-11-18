FONT='font-family="Noto Sans CJK KR, Apple SD Gothic Neo, Malgun Gothic, sans-serif"'
DEFS='<defs><marker id="ah" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto"><path d="M0,0 L14,7 L0,14 z" fill="#374151"/></marker></defs>'
def svg(W,H,body): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" {FONT}><rect width="100%" height="100%" fill="#fff"/>{DEFS}{body}</svg>'
def text(x,y,t,size=18,anchor="middle",weight="400",fill="#111827"):
    return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}">{t}</text>'
def box(x,y,w,h,fill,lines,size=19,stroke="#374151",rx=10,weight="400"):
    o=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
    n=len(lines); lh=size+6; y0=y+h/2-(n-1)*lh/2+size*0.35
    for i,l in enumerate(lines): o+=text(x+w/2,y0+i*lh,l,size,weight=weight if i==0 else "400")
    return o
def arrow(x1,y1,x2,y2,label=None,dash=False,lx=None,ly=None,lsize=16,anchor="middle"):
    d=' stroke-dasharray="7,5"' if dash else ''
    o=f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#374151" stroke-width="2"{d} marker-end="url(#ah)"/>'
    if label:
        lx=lx if lx is not None else (x1+x2)/2; ly=ly if ly is not None else (y1+y2)/2-8
        o+=text(lx,ly,label,lsize,anchor=anchor,fill="#374151")
    return o

# ---------- 한눈에 ----------
b=[]
W=1100
b.append(box(330,20,440,56,"#f3f4f6",["클라이언트 · curl, 브라우저, 다른 서버"]))
b.append(arrow(550,76,550,128,"POST /query",lx=560,ly=108,anchor="start"))
b.append(f'<rect x="40" y="130" width="1020" height="230" rx="14" fill="#eaf4ff" stroke="#93c5fd" stroke-width="2"/>')
b.append(text(60,162,"Phase 3 · server.py  —  받기·보내기는 스레드 4개가 동시에 (lock 밖)",19,"start","700","#1d4ed8"))
b.append(box(300,180,500,50,"#ffffff",["대기열 16칸 · 꽉 차면 바로 503"]))
xs=[100,345,590,835]
for i,x in enumerate(xs):
    b.append(box(x,270,165,50,"#9ecbff",[f"스레드 {i+1}"],weight="700"))
    b.append(arrow(550,230,x+82,268))
b.append(text(1040,162,"5초 넘게 안 보내면 408로 끊음",15,"end",fill="#6b7280"))
for x in xs: b.append(arrow(x+82,320,550,398))
b.append(f'<polygon points="330,400 770,400 800,430 770,460 330,460 300,430" fill="#ffd8a8" stroke="#c2410c" stroke-width="2"/>')
b.append(text(550,437,"🔒 engine.py lock · 한 번에 한 요청만 실행",20,weight="700",fill="#7c2d12"))
b.append(arrow(550,460,550,500,"engine.execute(sql)",lx=560,ly=486,anchor="start"))
b.append(f'<rect x="40" y="502" width="1020" height="300" rx="14" fill="#fff7ed" stroke="#fdba74" stroke-width="2"/>')
b.append(text(60,532,"실행 (lock 안)",19,"start","700","#c2410c"))
b.append(box(240,548,620,62,"#ffffff",["Phase 1 · SQL 처리기: 파서 → 실행기","열·타입 확인, 경로 선택"],size=18,weight="700"))
b.append(box(90,660,360,62,"#c7f0d0",["Phase 2 · B+ 트리 (메모리)","id → 파일 위치"],size=18,weight="700"))
b.append(arrow(400,610,290,658,"id 조건",lx=300,ly=640,anchor="end"))
# 파일 (원통)
fx,fy,fw,fh=600,690,320,80
b.append(f'<path d="M{fx},{fy+12} a{fw/2},12 0 0,1 {fw},0 v{fh-24} a{fw/2},12 0 0,1 -{fw},0 z" fill="#f3f4f6" stroke="#374151" stroke-width="1.5"/><ellipse cx="{fx+fw/2}" cy="{fy+12}" rx="{fw/2}" ry="12" fill="#e5e7eb" stroke="#374151" stroke-width="1.5"/>')
b.append(text(fx+fw/2,fy+50,"users.tbl · 한 줄에 한 행",18,weight="700"))
b.append(arrow(450,700,598,725,"그 줄만 읽기",lx=520,ly=700))
b.append(arrow(720,610,760,686,"그 밖의 조건: 전체 스캔",lx=760,ly=648,anchor="start"))
open("overview.svg","w").write(svg(W,820,"".join(b)))

# ---------- 요청 흐름 ----------
lanes=["서버","엔진","파서","실행기","B+ 트리","users.tbl"]
LX=[100,270,440,610,780,950]; W=1060
b=[]
for x,n in zip(LX,lanes): b.append(box(x-70,20,140,48,"#f3f4f6",[n],weight="700"))
msgs=[(0,1,"execute(SQL 덩어리)",0),("L",),(1,2,"parse",0),(2,1,"[Insert, Select]",1),(1,3,"Insert",0),(3,5,"끝에 한 줄 쓰기",0),(5,3,"위치 0",1),(3,4,"id 1 → 위치 0",0),(3,1,"새 id 1",1),("N","dict로 바꿔 목록에 추가"),
      (1,3,"Select id = 1",0),(3,4,"id 1 찾기",0),(4,3,"위치 0",1),(3,5,"위치 0 한 줄 읽기",0),(5,3,"1, 현지, 25",1),(3,1,"찾은 행",1),("N","dict로 바꿔 목록에 추가"),("E",),(1,0,"결과 목록 → JSON 응답",1)]
y=110; num=0; lock_top=None; body=[]
for m in msgs:
    if m[0]=="L": lock_top=y-8; body.append(("lockT",y)); y+=30; continue
    if m[0]=="E": body.append(("lockB",y-10)); y+=20; continue
    if m[0]=="N":
        body.append(box(LX[1]-110,y-20,220,34,"#fef3c7",[m[1]],size=15,stroke="#d97706",rx=6)); y+=46; continue
    a,c,l,d=m; num+=1
    x1,x2=LX[a],LX[c]; s=1 if x2>x1 else -1
    body.append(arrow(x1+s*14,y,x2-s*4,y,dash=bool(d)))
    body.append(text((x1+x2)/2+s*8,y-12,l,16,fill="#111827"))
    body.append(f'<circle cx="{x1}" cy="{y}" r="12" fill="#374151"/>'+text(x1,y+5,str(num),13,weight="700",fill="#fff"))
    y+=46
H=y+20
lt=[v for k,v in [(t[0],t[1]) for t in body if isinstance(t,tuple)] if k=="lockT"][0]
lb=[v for k,v in [(t[0],t[1]) for t in body if isinstance(t,tuple)] if k=="lockB"][0]
b.append(f'<rect x="{LX[1]-125}" y="{lt-22}" width="{LX[5]-LX[1]+205}" height="{lb-lt+30}" rx="12" fill="#fff1e0" stroke="#fdba74" stroke-width="2"/>')
b.append(text((LX[1]+LX[5])/2,lt+2,"🔒 lock 안: 한 번에 한 요청만",17,weight="700",fill="#c2410c"))
for x in LX: b.append(f'<line x1="{x}" y1="68" x2="{x}" y2="{H-10}" stroke="#d1d5db" stroke-width="2"/>')
for t in body:
    if isinstance(t,str): b.append(t)
open("request_flow.svg","w").write(svg(W,H,"".join(b)))
