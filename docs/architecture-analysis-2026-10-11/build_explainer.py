"""Rebuild the code inventory, diagrams and narrated architecture video locally.

Requires Pillow and imageio-ffmpeg (available in backend/.venv), plus the supplied
synthesize.ps1 on Windows. Never reads private databases or environment files.
Run: backend/.venv/Scripts/python.exe docs/architecture-analysis-2026-10-11/build_explainer.py prepare
Then: powershell -File docs/architecture-analysis-2026-10-11/synthesize.ps1
Then: backend/.venv/Scripts/python.exe docs/architecture-analysis-2026-10-11/build_explainer.py encode
"""
from pathlib import Path
import ast
import hashlib
import html
import json
import math
import re
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
W, H = 1600, 900
BG = '#101b2c'
PANEL = '#1b2c43'
WHITE = '#f2f6fc'
MUTED = '#bac9dc'
BLUE = '#74c8f8'
GREEN = '#7bdbc1'
AMBER = '#ffd180'

SCENES = [
    dict(title='Jarvis: the whole project', tag='01 / PURPOSE', diagram='overview',
         bullets=['Personal Android assistant', 'Conversation + phone observations + file retrieval', 'Flutter / Kotlin / FastAPI / LangGraph'],
         narration="Jarvis is a personal Android assistant that combines chat with observations from your phone. It can manage notes and reminders, explain sampled activity history, work with Google Calendar, and retrieve information from Drive files. Think of it as a phone application connected to a modular Python backend, with a separate embedding service and an indexing worker. This explanation follows the current local code. It does not verify which revision is running in the cloud."),
    dict(title='The phone has two layers', tag='02 / FRONTEND', diagram='phone',
         bullets=['Flutter: five main tabs and application services', 'Kotlin: sensors, background work, FCM and alarms', 'Method channels connect the layers'],
         narration="The visible interface is built with Flutter. Its main tabs are Chat, Activity, Reminders, Notes, and Settings. Singleton services and Flutter notifiers manage transport, local data, sensors and Google connections. Underneath, Kotlin handles Android capabilities that need to work when Flutter is closed: activity recognition, background location, upload workers, push messages and reminder alarms. Method channels connect these layers. The frontend is therefore more than the screens. Native Android code is an essential part of its reliability."),
    dict(title='Offline storage and telemetry', tag='03 / EDGE DATA', diagram='queues',
         bullets=['Mobile SQLite: app records and Flutter event outbox', 'SharedPreferences: native background event queue', 'CSV + JSON: explicit sensor recordings'],
         narration="The phone stores app records in a local SQLite database. Flutter telemetry also has a SQLite outbox. Native background events use a different queue: a JSON array committed to SharedPreferences. This differs from the README, which describes that native queue as SQLite. WorkManager uploads queued events and retries failures while preserving their identifiers. Explicit sensor recordings produce CSV files and JSON summaries. These recordings are distinct from the journey sessions and activity intervals reconstructed by the backend. Offline capture is supported, but cloud chat and integrations still need connectivity."),
    dict(title='FastAPI coordinates the work', tag='04 / BACKEND', diagram='backend',
         bullets=['REST: telemetry, CRUD, sync and file operations', 'SSE: chat progress, results and device proposals', 'Domain logic and agents share one backend'],
         narration="The backend uses FastAPI to expose telemetry, commands, reminders, notes, synchronization, recording backups and file operations. Chat progress uses server sent events, with request status and reconnect support. This is not a WebSocket design. The API invokes a cached LangGraph workflow and deterministic domain services. Tier one and tier two are reasoning paths inside the same application, not independent deployed microservices. Blocking graph and cloud operations are moved to worker threads in important async endpoints. A separate embedding service and an indexing job handle file retrieval workloads."),
    dict(title='Two reasoning paths', tag='05 / LANGGRAPH', diagram='graph',
         bullets=['Tier 1: resolve ambiguous physical evidence', 'Tier 2: choose conversational tools', 'Agent tools feed results back into bounded loops'],
         narration="Every graph run begins with normalization and context loading. Context events go through an evidence gate. Ordinary sparse observations can use the deterministic reducer directly, while ambiguous feature bearing telemetry can invoke tier one and its tools. Commands go through intent routing. Greetings have a fast path; other requests enter tier two and its tool loop. Chat now loads context on demand, so a file question does not automatically fetch GPS or nearby places. Both branches eventually persist their results. Journey statuses are Created, Active, Paused, Resumed, Completed and Expired; parking and shop context are separate concepts."),
    dict(title='Where each kind of data lives', tag='06 / DATABASES', diagram='stores',
         bullets=['SQLite: phone records and backend local state', 'Firestore: cloud records, requests, budgets and outbox', 'Storage: bytes; Chroma: semantic retrieval'],
         narration="There is no PostgreSQL or MySQL server in this checkout. SQLite holds device data and backend local state. Firestore holds cloud records, context memory, command requests, notifications, budgets and indexing metadata. Cloud Storage holds recording backups and staged imports. Chroma stores derived file chunks and their vectors. Firestore does not have one uniform layout: reminders and chats use top level collections with user fields, while context and requests use collections under a user document. Some task tools write only to backend SQLite, so their cloud durability needs attention. A local table does not automatically imply a durable cloud copy."),
    dict(title='Chat and Calendar execution', tag='07 / REQUEST FLOW', diagram='command',
         bullets=['Stable request ID + Firestore claim + execution lease', 'Cloud Tasks continue work after phone disconnects', 'Calendar proposal -> approval -> phone-side Google call'],
         narration="A command starts with a stable request identifier and a Firestore claim. Fingerprints reject reuse of an identifier for a different message, and leases prevent competing command execution. Cloud Tasks can continue the work when the phone connection ends. The device receives progress and proposals through the command stream. For Calendar writes, the phone shows a concrete proposal, obtains approval, calls Google using its own authorization, and returns the result. ETags and receipts protect against changed events and uncertain repeat writes. Ordinary requested notes and reminders are currently allowlisted without a second approval dialog. Older documentation says otherwise."),
    dict(title='Context becomes a reminder', tag='08 / AUTOMATION', diagram='reminder',
         bullets=['Persist observed event before evaluating rules', 'Fresh evidence gates immediate context alerts', 'Transactional outbox -> FCM or polling -> acknowledgement'],
         narration="A background phone event is persisted before reminder rules are evaluated. Immediate context alerts require fresh matching evidence; the ingestion route uses a five minute freshness window. Older uploads can still improve history without triggering an immediate alert. A one shot reminder and its notification outbox entry are committed together in Firestore. Push delivery or polling brings the alert to the phone, and acknowledgement prevents ordinary duplicates. Activity delay reminders use durable timer state and task callbacks. Sensor gaps remain gaps. The timeline does not prove continuous exercise, and Android scheduling can delay background work."),
    dict(title='Drive search is a separate pipeline', tag='09 / FILE RETRIEVAL', diagram='drive',
         bullets=['Drive source -> staging -> format readers -> chunks', 'Pinned model -> 768-dimensional normalized vectors', 'Owner / account / version filters select evidence'],
         narration="Drive retrieval has its own pipeline. The phone downloads or exports an authorized source, registers metadata, and uploads bytes to private staging. A leased cloud indexing job reads formats, creates bounded chunks, and asks the separate embedding service for vectors. The code pins the model revision and checks that vectors have seven hundred and sixty eight dimensions. Chroma stores the derived evidence with owner, account and source version metadata. Queries embed the question and retrieve filtered evidence. Successful staged sources are deleted; failed ones remain for retry. Large imports also have a local bulk workflow. Direct multimodal file analysis is another path, not the same as indexing."),
    dict(title='The main architectural risks', tag='10 / FINDINGS', diagram='risks',
         bullets=['API identity is currently one shared user', 'Sync can acknowledge without confirmed cloud writes', 'Empty error snapshots can cause destructive reconciliation'],
         narration="The largest boundary is identity. The backend currently returns the same local user for every caller; the mobile user header is not authenticated account identity. File capabilities and Calendar sessions protect specific paths, but they do not isolate all API data. Synchronization also has important gaps. The push route can acknowledge records without confirming Firestore persistence. Some cloud readers convert errors into empty lists, while the phone interprets missing remote records as deletions. Additional concerns include instance local tasks, full collection scans, concurrent session updates, an unbounded direct index upload path, and different frontend and native backend URLs."),
    dict(title='Reliability, cost and next decisions', tag='11 / ASSESSMENT', diagram='next',
         bullets=['Strengths: durable IDs, outbox, receipts, selective AI', 'Decide data authority and sync guarantees first', 'AI allowance does not cap cloud infrastructure costs'],
         narration="The project already has useful reliability mechanisms: stable event and request IDs, command leases, transactional notifications, cautious write receipts, and selective model use. The AI allowance uses durable reservations in Cloud Run and resets by Indian time, but this does not cap indexing, compute, storage or database costs. Before expanding the system, decide whether it is single user or multi user, choose an authoritative durable store for every entity, and define exactly what a sync acknowledgement guarantees. Then test outages, retries, races and permission denial. The companion report provides detailed diagrams, source evidence and a prioritized action list."),
]


def font(size, bold=False):
    path = Path('C:/Windows/Fonts') / ('segoeuib.ttf' if bold else 'segoeui.ttf')
    return ImageFont.truetype(str(path), size)


def wrap(draw, text, f, width):
    lines, line = [], ''
    for word in text.split():
        candidate = f'{line} {word}'.strip()
        if draw.textlength(candidate, font=f) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def block(draw, text, xy, width, size=27, color=WHITE, bold=False, gap=9):
    f = font(size, bold)
    x, y = xy
    for line in wrap(draw, text, f, width):
        draw.text((x, y), line, font=f, fill=color)
        y += size + gap
    return y


def node(draw, rect, title, detail='', accent=BLUE, size=27):
    x, y, x2, y2 = rect
    draw.rounded_rectangle(rect, radius=15, fill=PANEL, outline='#3c526e', width=2)
    draw.rounded_rectangle((x, y, x+6, y2), radius=3, fill=accent)
    ny = block(draw, title, (x+20, y+17), x2-x-40, size=size, bold=True)
    if detail:
        block(draw, detail, (x+20, ny+8), x2-x-40, size=21, color=MUTED, gap=6)


def arrow(draw, points, color=BLUE, width=3):
    draw.line(points, fill=color, width=width)
    a, b = points[-2], points[-1]
    angle = math.atan2(b[1]-a[1], b[0]-a[0])
    pts = [b, (b[0]-13*math.cos(angle-.45), b[1]-13*math.sin(angle-.45)),
           (b[0]-13*math.cos(angle+.45), b[1]-13*math.sin(angle+.45))]
    draw.polygon(pts, fill=color)


def chain(draw, labels, y=430, details=None, x=75, end=1525, height=160, accent=BLUE):
    n = len(labels)
    gap = 34
    width = (end-x-gap*(n-1))/n
    for i, label in enumerate(labels):
        left = int(x+i*(width+gap))
        node(draw, (left, y, int(left+width), y+height), label,
             (details or ['']*n)[i], accent=accent)
        if i < n-1:
            arrow(draw, [(int(left+width)+2, y+height//2), (int(left+width+gap)-3, y+height//2)])


def overview(draw, y=290):
    # Three lanes make relationships readable without a dense arrow crossing.
    chain(draw, ['Android phone', 'FastAPI + LangGraph', 'Durable cloud data'], y,
          ['Flutter UI + Kotlin background work', 'Tier 1 / Tier 2 + deterministic domain logic', 'Firestore records + Cloud Storage bytes'], height=160)
    for i, (title, detail) in enumerate([
        ('Google Calendar / Drive', 'OAuth calls execute on the phone'),
        ('Separate embedding runtime', 'Pinned model + normalized 768D vectors'),
        ('Chroma Cloud', 'File chunks + semantic search')]):
        node(draw, (75+i*494, y+215, 535+i*494, y+375), title, detail, accent=GREEN)
    arrow(draw, [(305,y+213),(305,y+162)], color=GREEN)
    arrow(draw, [(800,y+162),(800,y+213)], color=GREEN)
    arrow(draw, [(1032,y+297),(1060,y+297)], color=GREEN)
    draw.text((1090,y+387),'Index job writes; API queries',font=font(20),fill=GREEN)
    draw.text((75, y+423), 'Cloud Tasks wake the backend. FCM wakes the phone. Vectors reach Chroma through the index job.', font=font(23), fill=MUTED)


def scene_diagram(draw, kind):
    if kind == 'overview':
        overview(draw, 360)
    elif kind == 'phone':
        chain(draw, ['Flutter UI', 'Dart services', 'Kotlin / Android'], details=['Chat | Activity | Reminders | Notes | Settings', 'Transport, local state, sensors, Google APIs', 'WorkManager, receivers, monitoring, FCM, alarms'])
        block(draw, 'Native background work survives an ordinary Flutter screen close.', (75, 665), 1450, color=GREEN, size=30)
    elif kind == 'queues':
        chain(draw, ['Flutter events', 'SQLite outbox', 'FastAPI'], details=['Visible app / recordings', 'Stable event IDs + retry', 'Context ingestion'])
        chain(draw, ['Native observations', 'SharedPreferences', 'WorkManager'], y=645, height=140, details=['Activity and location', 'Disk-backed JSON queue', 'Upload + recovery'], accent=GREEN)
    elif kind == 'backend':
        chain(draw, ['API routers', 'LangGraph', 'Domain services', 'Storage adapters'], details=['REST + SSE', 'Agent / tool loops', 'History + sessions + rules', 'SQLite / Firestore / files'])
        block(draw, 'One modular backend; separate embedding and index execution.', (75, 665), 1400, size=30, color=GREEN)
    elif kind == 'graph':
        node(draw, (75, 430, 345, 570), 'verify + load', 'Normalize and choose context scope')
        node(draw, (435, 370, 915, 510), 'Context evidence -> Tier 1 if needed', 'Reducer -> semantic context', size=25)
        node(draw, (435, 600, 915, 745), 'Intent -> Tier 2 + tool loop', 'Greeting fast path; on-demand reads', size=25)
        node(draw, (1030, 465, 1515, 635), 'persist', 'Local records + relevant cloud copies')
        arrow(draw, [(345, 470), (390, 470), (390, 440), (435, 440)])
        arrow(draw, [(345, 530), (390, 530), (390, 670), (435, 670)])
        arrow(draw, [(915, 440), (980, 440), (980, 510), (1030, 510)])
        arrow(draw, [(915, 670), (980, 670), (980, 590), (1030, 590)])
    elif kind == 'stores':
        for i, (name, desc) in enumerate([
            ('Phone SQLite', 'Offline app records'), ('Backend SQLite', 'Local state / cache; task gap'),
            ('Firestore', 'Cloud records + control state'), ('Cloud Storage', 'Recording / staged source bytes'),
            ('Chroma Cloud', 'Derived chunks + vectors'), ('Google services', 'Source files + calendar events')]):
            col, row = i % 3, i // 3
            node(draw, (75+col*490, 410+row*200, 535+col*490, 575+row*200), name, desc, accent=GREEN if i>=3 else BLUE)
    elif kind == 'command':
        chain(draw, ['Phone request', 'Firestore claim', 'Cloud Task', 'Tier 2 tools'], details=['Stable request ID', 'Fingerprint + lease', 'Independent execution', 'Read / act / report'])
        chain(draw, ['Calendar proposal', 'Device approval', 'Google API', 'Return result'], y=640, height=145, details=['Action ID + expiry', 'Exact change shown', 'Phone OAuth + ETag', 'Receipt / result'], accent=GREEN)
    elif kind == 'reminder':
        chain(draw, ['Phone event', 'Persist', 'Fresh rule match', 'Outbox + alert'], details=['Queue before upload', 'Preserve event time', 'Deterministic evaluation', 'FCM / polling / ack'])
        block(draw, 'History can use late events. Immediate alerts need fresh evidence.', (75, 675), 1450, size=30, color=GREEN)
    elif kind == 'drive':
        chain(draw, ['Drive export', 'Private staging', 'Indexing job', 'Embedding'], details=['Authorized on phone', 'Cloud Storage bytes', 'Readers + bounded chunks', 'Pinned revision / 768D'])
        chain(draw, ['File question', 'Query vector', 'Chroma filters', 'Source evidence'], y=640, height=145, details=['On-demand retrieval', 'Same model contract', 'Owner / account / version', 'Locators + coverage'], accent=GREEN)
    elif kind == 'risks':
        for i, (name, desc) in enumerate([
            ('Shared identity', 'Every API caller gets one UID'),
            ('Sync durability', 'Ack may precede cloud persistence'),
            ('Snapshot safety', 'Read errors can resemble deletions')]):
            node(draw, (75+i*490, 430, 535+i*490, 665), name, desc, accent=AMBER, size=30)
        block(draw, 'Also review: task durability, upload bounds, event races and endpoint configuration.', (75, 720), 1450, size=26, color=MUTED)
    elif kind == 'next':
        chain(draw, ['Choose identity', 'Define data authority', 'Specify sync contract'], details=['Personal / multiple users', 'Durable owner of each entity', 'Ack / conflicts / deletes'], accent=GREEN)
        block(draw, 'Then validate failures, permissions, retries, concurrency and operating cost.', (75, 690), 1450, size=30, color=GREEN)


def make_slide(scene, index):
    im = Image.new('RGB', (W,H), BG)
    draw = ImageDraw.Draw(im)
    draw.text((75, 42), scene['tag'], font=font(22, True), fill=BLUE)
    draw.text((75, 93), scene['title'], font=font(53, True), fill=WHITE)
    y = 183
    for bullet in scene['bullets']:
        draw.ellipse((78,y+11,88,y+21), fill=GREEN)
        y = block(draw, bullet, (105,y), 1420, size=27, color=MUTED, gap=5)+9
    scene_diagram(draw, scene['diagram'])
    draw.line([(75,842),(1525,842)], fill='#3c526e', width=2)
    draw.line([(75,842),(75+int(1450*(index+1)/len(SCENES)),842)], fill=BLUE, width=4)
    draw.text((75, 858), 'JARVIS  /  Code architecture review  /  11 October 2026', font=font(19), fill=MUTED)
    draw.text((1365,858), f'{index+1:02d} / {len(SCENES):02d}', font=font(19), fill=MUTED)
    im.save(OUT / 'slides' / f'{index:02d}.png')


def inventory():
    records=[]
    roots=[ROOT/'backend/src', ROOT/'mobile/lib', ROOT/'mobile/android/app/src/main/kotlin', ROOT/'embedding']
    for root in roots:
        for path in sorted(root.rglob('*')):
            if path.suffix not in {'.py','.dart','.kt'} or '__pycache__' in path.parts:
                continue
            content=path.read_text(encoding='utf-8-sig')
            entry={'path':path.relative_to(ROOT).as_posix(),'lines':len(content.splitlines()),
                   'sha256':hashlib.sha256(content.encode()).hexdigest()}
            if path.suffix=='.py':
                tree=ast.parse(content)
                entry['definitions']=[{'name':n.name,'line':n.lineno,'kind':type(n).__name__}
                                      for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
                entry['routes']=[]
                for n in ast.walk(tree):
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        for deco in n.decorator_list:
                            if isinstance(deco,ast.Call) and isinstance(deco.func,ast.Attribute) and deco.func.attr in {'get','put','post','patch','delete'} and deco.args and isinstance(deco.args[0],ast.Constant):
                                entry['routes'].append({'method':deco.func.attr.upper(),'declared_path':deco.args[0].value,'handler':n.name,'line':n.lineno})
            records.append(entry)
    tests={}
    for name,loc,suffix in [('backend',ROOT/'backend/tests','.py'),('mobile',ROOT/'mobile/test','.dart'),('embedding',ROOT/'embedding/tests','.py'),('android',ROOT/'mobile/android/app/src/test','.kt')]:
        tests[name]=[p.relative_to(ROOT).as_posix() for p in sorted(loc.rglob('*')) if p.suffix==suffix and '__pycache__' not in p.parts]
    result={'review_date':'2026-10-11','scope':'local source, not a live deployment audit','files':records,'test_files':tests}
    (OUT/'source-map.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Source files:',len(records),'Test files:',{k:len(v) for k,v in tests.items()})


def prepare():
    (OUT/'slides').mkdir(exist_ok=True)
    (OUT/'audio').mkdir(exist_ok=True)
    (OUT/'scenes.json').write_text(json.dumps(SCENES,indent=2),encoding='utf-8')
    (OUT/'video-transcript.md').write_text('# Jarvis architecture: video transcript\n\nEnglish narration synthesized locally with Microsoft Zira.\n\n'+
        '\n\n'.join(f"## {s['title']}\n\n{s['narration']}" for s in SCENES)+'\n',encoding='utf-8')
    for i,s in enumerate(SCENES):
        make_slide(s,i)
    im=Image.new('RGB',(W,H),BG)
    draw=ImageDraw.Draw(im)
    draw.text((75,55),'Jarvis architecture',font=font(58,True),fill=WHITE)
    draw.text((75,140),'Android edge + modular backend + file retrieval infrastructure',font=font(30),fill=MUTED)
    overview(draw,245)
    draw.text((75,740),'Phone persistence: SQLite + native SharedPreferences + recording files',font=font(26),fill=MUTED)
    draw.text((75,786),'Current API identity: shared local user. Cloud storage authority differs by entity.',font=font(26),fill=AMBER)
    im.save(OUT/'architecture.png')
    inventory()
    print('Prepared',len(SCENES),'slides and narration texts.')


def timestamp(t):
    ms=round(t*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'


def encode():
    import imageio_ffmpeg
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    (OUT/'segments').mkdir(exist_ok=True)
    offset=0
    chapters=[]
    captions=['WEBVTT','']
    for i,s in enumerate(SCENES):
        wav=OUT/'audio'/f'{i:02d}.wav'
        with wave.open(str(wav),'rb') as f:
            duration=f.getnframes()/f.getframerate()
        chapters.append({'title':s['title'],'start':round(offset,3),'duration':round(duration,3)})
        # Approximate sentence cue timing from each measured scene WAV.
        sentences=re.split(r'(?<=[.!?])\s+',s['narration'])
        weights=[len(x.split()) for x in sentences]
        position=offset
        for sentence,weight in zip(sentences,weights):
            end=position+duration*weight/sum(weights)
            captions.extend([f'{timestamp(position)} --> {timestamp(end)}',sentence,''])
            position=end
        subprocess.run([ffmpeg,'-v','error','-y','-loop','1','-framerate','1','-i',str(OUT/'slides'/f'{i:02d}.png'),
            '-i',str(wav),'-t',str(duration),'-vf','fade=t=in:st=0:d=0.25',
            '-r','12','-c:v','libx264','-preset','fast','-tune','stillimage','-crf','22','-pix_fmt','yuv420p',
            '-c:a','aac','-b:a','96k','-ar','24000','-movflags','+faststart',str(OUT/'segments'/f'{i:02d}.mp4')],check=True)
        offset+=duration
        print('Encoded',i+1,s['title'],f'{duration:.1f}s',flush=True)
    concat=OUT/'segments'/'concat.txt'
    concat.write_text('\n'.join(f"file '{i:02d}.mp4'" for i in range(len(SCENES))),encoding='utf-8')
    metadata=OUT/'segments'/'chapters.ffmeta'
    chapter_text=[';FFMETADATA1','title=Jarvis architecture explained','comment=Local source review, 11 October 2026; synthesized English narration']
    for c in chapters:
        chapter_text.extend(['[CHAPTER]','TIMEBASE=1/1000',f"START={round(c['start']*1000)}",f"END={round((c['start']+c['duration'])*1000)}",f"title={c['title']}"])
    metadata.write_text('\n'.join(chapter_text),encoding='utf-8')
    target=OUT/'jarvis-architecture-explained.mp4'
    subprocess.run([ffmpeg,'-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(metadata),
                    '-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',str(target)],check=True)
    (OUT/'captions.vtt').write_text('\n'.join(captions),encoding='utf-8')
    (OUT/'chapters.json').write_text(json.dumps(chapters,indent=2),encoding='utf-8')
    items=''.join(f'<button onclick="jump({c["start"]})">{timestamp(c["start"])[:8]} · {html.escape(c["title"])}</button>' for c in chapters)
    (OUT/'watch.html').write_text('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Jarvis architecture explained</title><style>
body{margin:0;background:#101b2c;color:#f2f6fc;font:17px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px}h1{margin-bottom:6px}p{color:#bac9dc}video,img{width:100%;border-radius:10px}nav{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}a{color:#74c8f8}.chapters{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:8px}button{background:#1b2c43;color:#f2f6fc;border:1px solid #3c526e;border-radius:7px;padding:13px;text-align:left;font:inherit;cursor:pointer}button:hover{background:#29405a}button:focus-visible{outline:3px solid #74c8f8}</style></head><body><main><h1>Jarvis architecture explained</h1>
<p>Code review · 11 October 2026 · English synthesized narration · approximately '''+str(round(offset/60,1))+''' minutes</p>
<video id="video" controls preload="metadata" poster="architecture.png"><source src="jarvis-architecture-explained.mp4" type="video/mp4"><track kind="captions" src="captions.vtt" srclang="en" label="English (approximate sentence timing)"></video>
<nav><a href="analysis.md">Full written analysis</a><a href="video-transcript.md">Narration transcript</a><a href="architecture.png">Architecture diagram</a><a href="source-map.json">Source evidence</a></nav><h2>Chapters</h2><div class="chapters">'''+items+'''</div><h2>Architecture at a glance</h2><img src="architecture.png" alt="Jarvis architecture: phone, FastAPI backend, cloud stores, Google integrations, embedding service and Chroma."><p>This explains the inspected local code, not a live deployment audit. Caption timestamps are estimated within each measured narration scene.</p></main><script>function jump(seconds){const v=document.getElementById('video');v.currentTime=seconds;v.play().catch(()=>{});v.scrollIntoView({behavior:'smooth',block:'center'});}</script></body></html>''',encoding='utf-8')
    print(json.dumps({'video':str(target),'duration_seconds':round(offset,2),'size_bytes':target.stat().st_size,'resolution':[W,H]}),flush=True)


if __name__=='__main__':
    {'prepare':prepare,'encode':encode}[sys.argv[1]]()
