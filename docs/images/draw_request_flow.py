exec(open(__file__.replace("draw_request_flow.py","draw_readme_figures.py")).read().split("# ---------- 한눈에 ----------")[0])
lanes=[("서버","server.py"),("엔진","engine.py"),("파서","parser.py"),("실행기","executor.py"),("B+ 트리","bptree.py"),("파일","storage.py → users.tbl")]
LX=[110,330,560,790,1010,1220]; W=1360
msgs=[
 ("M",0,1,['execute("INSERT ... SELECT ...")','SQL 글자 한 덩어리'],0),
 ("L",),
 ("M",1,2,["parse(sql)"],0),
 ("M",2,1,["[Insert 객체, Select 객체]"],1),
 ("NE",["results = [ ]"]),
 ("M",1,3,["execute(Insert 객체)"],0),
 ("NX",["열·타입 확인","다음 id = 1"]),
 ("M",3,5,['끝에 한 줄 쓰기 "1 현지 25"'],0),
 ("M",5,3,["위치 0"],1),
 ("M",3,4,["insert(id 1, 위치 0)"],0),
 ("M",3,1,['QueryResult(columns=("id",), rows=((1,),))'],1),
 ("NE",["dict로 바꿔 results에 추가","results = [ {type: insert, id: 1} ]"]),
 ("M",1,3,["execute(Select 객체)"],0),
 ("M",3,4,["search(id 1)"],0),
 ("M",4,3,["위치 0"],1),
 ("M",3,5,["위치 0의 한 줄 읽기"],0),
 ("M",5,3,['(1, "현지", 25)'],1),
 ("M",3,1,["QueryResult(columns, rows, used_index=True)"],1),
 ("NE",["dict로 바꿔 results에 추가","results = [ {insert...}, {type: select, rows: [[1, 현지, 25]], used_index: true} ]"]),
 ("E",),
 ("M",1,0,["results (dict 2개짜리 목록)"],1),
 ("NS",["json.dumps → HTTP 200 응답"]),
]
b=[]; body=[]; y=150; num=0; lt=lb=None
for m in msgs:
    k=m[0]
    if k=="L": lt=y-6; y+=44; continue
    if k=="E": lb=y; y+=40; continue
    if k in("NE","NX","NS"):
        lines=m[1]; h=22*len(lines)+14
        w=max(len(t) for t in lines)*9+40
        if k=="NE": x=LX[1]-150; w=max(w,300)
        elif k=="NX": x=LX[3]+20
        else: x=LX[0]-90
        body.append(box(x,y-16,w,h,"#fef3c7",lines,size=15,stroke="#d97706",rx=6))
        y+=h+22; continue
    _,a,c,lines,d=m; num+=1
    x1,x2=LX[a],LX[c]; s=1 if x2>x1 else -1
    ly=y-12-(len(lines)-1)*20
    for i,t in enumerate(lines): body.append(text((x1+x2)/2,ly+i*20,t,16 if i==0 else 14,fill="#111827" if i==0 else "#6b7280"))
    body.append(arrow(x1+s*14,y,x2-s*4,y,dash=bool(d)))
    body.append(f'<circle cx="{x1}" cy="{y}" r="12" fill="#374151"/>'+text(x1,y+5,str(num),13,weight="700",fill="#fff"))
    y+=56 if len(lines)==1 else 66
H=y+10
b.append(f'<rect x="{LX[1]-170}" y="{lt-24}" width="{LX[5]-LX[1]+260}" height="{lb-lt+24}" rx="12" fill="#fff1e0" stroke="#f97316" stroke-width="2"/>')
titles=[text(LX[1]-150,lt+2,"🔒 engine.py: execute()가 시작되며 lock을 잡음 → 이 상자 안은 한 번에 한 요청만",17,"start","700","#c2410c"),
        text(LX[1]-150,lb-10,"🔓 execute()가 끝나며 lock을 놓음 → 다음 요청이 들어옴",17,"start","700","#c2410c")]
for x,(n,f) in zip(LX,lanes):
    b.append(box(x-105,20,210,62,"#f3f4f6",[n,f],size=17,weight="700"))
    b.append(f'<line x1="{x}" y1="82" x2="{x}" y2="{H-10}" stroke="#d1d5db" stroke-width="2"/>')
b+=body
for t,(tx,ty) in zip(titles,[(LX[1]-158,lt-18),(LX[1]-158,lb-30)]): b.append(f'<rect x="{tx}" y="{ty}" width="760" height="28" fill="#fff1e0"/>'+t)
open("request_flow.svg","w").write(svg(W,H,"".join(b)))
