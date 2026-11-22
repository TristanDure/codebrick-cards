from __future__ import annotations
import argparse, hashlib, html, json, re, sys, time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
try:
    from .co_pipeline_corrections import repair_summary_text
except ImportError:
    from co_pipeline_corrections import repair_summary_text

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache' / 'html'
DATA = ROOT / 'data'
SOURCES = [
    {'id':'os','name':'操作系统','prefix':'os-blog','base':'https://www.codebrick.tech/os-blog/','extension':''},
    {'id':'co','name':'计算机组成原理','prefix':'co-blog','base':'https://www.codebrick.tech/co-blog/','extension':'.html'},
    {'id':'cn','name':'计算机网络','prefix':'cn-blog','base':'https://www.codebrick.tech/cn-blog/','extension':'.html'},
    {'id':'ds','name':'数据结构','prefix':'ds-blog','base':'https://www.codebrick.tech/ds-blog/','extension':'.html'},
]
VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
SKIP={'script','style','noscript','button','nav'}

class Node:
    def __init__(self, tag, attrs=()): self.tag,self.attrs,self.children=tag,dict(attrs),[]
class Tree(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.root=Node('root'); self.stack=[self.root]
    def handle_starttag(self,tag,attrs):
        n=Node(tag,((k,v or '') for k,v in attrs)); self.stack[-1].children.append(n)
        if tag not in VOID: self.stack.append(n)
    def handle_startendtag(self,tag,attrs): self.stack[-1].children.append(Node(tag,attrs))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag: del self.stack[i:]; break
    def handle_data(self,data):
        if data: self.stack[-1].children.append(data)
def walk(n):
    yield n
    for c in n.children:
        if isinstance(c,Node): yield from walk(c)
def text(n):
    if isinstance(n,str): return n
    if 'header-anchor' in n.attrs.get('class','').split(): return ''
    if n.tag=='svg':
        label=clean(n.attrs.get('aria-label','') or n.attrs.get('role','') or n.attrs.get('title',''))
        return f'[SVG公式/图示：{label}]' if label else '[SVG公式/图示需人工核对原文]'
    if n.tag=='canvas': return '[交互图示需人工核对原文]'
    if n.tag=='math':
        annotations=[node for node in walk(n) if node.tag=='annotation' and 'tex' in node.attrs.get('encoding','').lower()]
        if annotations:
            tex=clean(''.join(text(child) for child in annotations[0].children))
            if tex: return f'[公式：{tex}]'
        def math_text(node):
            if isinstance(node,str): return node
            values=[math_text(child) for child in node.children]
            value=''.join(values)
            if node.tag=='mfrac' and len(values)>=2: return f'({values[0]})/({values[1]})'
            if node.tag=='msup' and len(values)>=2: return f'{values[0]}^{{{values[1]}}}'
            if node.tag=='msub' and len(values)>=2: return f'{values[0]}_{{{values[1]}}}'
            if node.tag=='msubsup' and len(values)>=3: return f'{values[0]}_{{{values[1]}}}^{{{values[2]}}}'
            if node.tag=='msqrt': return f'√({value})'
            if node.tag=='mroot' and len(values)>=2: return f'root[{values[1]}]({values[0]})'
            if node.tag=='mfenced': return f'({value})'
            return value
        rendered=clean(math_text(n))
        return f'[公式：{rendered}]' if rendered else '[MathML公式需人工核对原文]'
    if n.tag in SKIP: return ''
    if n.tag=='ul' or n.tag=='ol':
        items=[c for c in n.children if isinstance(c,Node) and c.tag=='li']
        return '\n'.join((f'{i}. ' if n.tag=='ol' else '• ')+''.join(text(c) for c in item.children) for i,item in enumerate(items,1))
    if n.tag=='table':
        rows=[x for x in walk(n) if x.tag=='tr']
        rendered=[]
        for index,row in enumerate(rows,1):
            cells=[cell for cell in row.children if isinstance(cell,Node) and cell.tag in {'th','td'}]
            values=' | '.join(clean(''.join(text(c) for c in cell.children)) for cell in cells)
            if values: rendered.append(('表头' if any(cell.tag=='th' for cell in cells) else f'行{index}')+'：'+values)
        return '【表格：'+'；'.join(rendered)+'】'
    if n.tag=='img':
        alt=clean(n.attrs.get('alt',''))
        src=clean(n.attrs.get('src',''))
        label=f'[图示：{alt}]' if alt else '[图片需人工核对原文]'
        return label+(f'（资源：{src}）' if src else '')
    s=''.join(text(c) for c in n.children)
    if n.tag=='a':
        label=clean(s) or clean(n.attrs.get('aria-label','')) or clean(n.attrs.get('title',''))
        title=clean(n.attrs.get('title',''))
        href=clean(n.attrs.get('href',''))
        if title and title!=label: label+=f'（说明：{title}）'
        if href and href!=label: label+=f'（链接：{href}）'
        return label
    if n.tag=='sup': return f'^{{{s}}}'
    if n.tag=='sub': return f'_{{{s}}}'
    if n.tag in {'td','th'}: return ' | '+s
    return ('\n'+s+'\n') if n.tag in {'p','li','blockquote','pre','h1','h2','h3','h4','h5','h6','tr'} else s
def clean(s):
    return '\n'.join(x for x in (re.sub(r'\s+',' ',z).strip() for z in html.unescape(s).replace('\xa0',' ').replace('\u200b','').splitlines()) if x)
def parse_article(raw,url):
    p=Tree(); p.feed(raw)
    doc=next((n for n in walk(p.root) if 'vp-doc' in n.attrs.get('class','').split()),None)
    if not doc: raise ValueError('正文容器 .vp-doc 不存在')
    blocks=[]
    def add_block(node,tag,value):
        if not value: return
        unit_texts=[]
        if tag in {'ul','ol'}:
            items=[child for child in node.children if isinstance(child,Node) and child.tag=='li']
            unit_texts=[(f'{index}. ' if tag=='ol' else '• ')+clean(''.join(text(child) for child in item.children)) for index,item in enumerate(items,1)]
        elif tag=='table':
            for row in [item for item in walk(node) if item.tag=='tr']:
                cells=[cell for cell in row.children if isinstance(cell,Node) and cell.tag in {'th','td'}]
                rendered=' | '.join(clean(''.join(text(child) for child in cell.children)) for cell in cells)
                if rendered: unit_texts.append(('表头：' if any(cell.tag=='th' for cell in cells) else f'行{len(unit_texts)+1}：')+rendered)
        if not unit_texts: unit_texts=[value]
        blocks.append({'tag':tag,'text':value,'unitTexts':unit_texts,'id':node.attrs.get('id',''),'blockIndex':len(blocks)+1,
            'href':node.attrs.get('href',''),'title':node.attrs.get('title',''),'class':node.attrs.get('class',''),
            'src':node.attrs.get('src',''),'alt':node.attrs.get('alt','')})
    semantic_tags={'h1','h2','h3','h4','h5','h6','p','li','ul','ol','blockquote','pre','table','svg','canvas','math','a','img'}
    def has_semantic_child(node):
        for child in node.children:
            if not isinstance(child,Node) or child.tag in SKIP: continue
            if child.tag in semantic_tags or has_semantic_child(child): return True
        return False
    def visit(n):
        for c in n.children:
            if not isinstance(c,Node) or c.tag in SKIP: continue
            if c.tag=='a':
                classes=set(c.attrs.get('class','').split())
                if 'header-anchor' in classes or c.attrs.get('aria-hidden')=='true': continue
                add_block(c,'a',clean(text(c)))
            elif c.tag in {'h1','h2','h3','h4','h5','h6','p','li','ul','ol','blockquote','pre','table','svg','canvas','math'}:
                add_block(c,c.tag,clean(text(c)))
            elif c.tag=='img':
                add_block(c,'img',text(c))
            elif c.tag=='span' and c.attrs.get('aria-hidden')!='true' and not has_semantic_child(c):
                add_block(c,'component-text',clean(text(c)))
            elif (c.attrs.get('aria-label') or c.attrs.get('role')=='img') and not has_semantic_child(c):
                label=clean(c.attrs.get('aria-label') or text(c))
                add_block(c,'accessible-component',label)
            else: visit(c)
    visit(doc)
    title=next((x['text'] for x in blocks if x['tag']=='h1'),'')
    if not title:
        m=re.search(r'<title>(.*?)</title>',raw,re.I|re.S); title=clean(m.group(1)) if m else url.rsplit('/',1)[-1]
    return {'title':title,'url':url,'blocks':blocks}
def sections(article):
    out=[]; cur=None; intro=[]; intro_units=[]; heading_stack=[]
    def add_content(section,block):
        unit={key:block.get(key,'') for key in ('tag','text','id','blockIndex','href','title','class','src','alt')}
        unit['unitTexts']=block.get('unitTexts',[block['text']])
        section['content'].append(block['text'])
        section['sourceUnits'].append(unit)
    for b in article['blocks']:
        if b['tag'] in {'h2','h3','h4','h5','h6'}:
            if cur: out.append(cur)
            level=int(b['tag'][1])
            heading_stack=[item for item in heading_stack if item[0]<level]
            heading_stack.append((level,b['text']))
            cur={'heading':b['text'],'headingPath':' / '.join(item[1] for item in heading_stack),'anchor':b['id'],'level':level,'content':[],'sourceUnits':[]}
        elif cur and b['tag']!='h1': add_content(cur,b)
        elif not cur and b['tag']!='h1':
            intro.append(b['text'])
            unit={key:b.get(key,'') for key in ('tag','text','id','blockIndex','href','title','class','src','alt')}
            unit['unitTexts']=b.get('unitTexts',[b['text']])
            intro_units.append(unit)
    if cur: out.append(cur)
    if intro:
        out.insert(0, {'heading':'导言','headingPath':'导言','anchor':'','level':2,'content':intro,'sourceUnits':intro_units})
    if not out:
        out.append({'heading':'未识别章节结构（需人工核对）','headingPath':'未识别章节结构（需人工核对）','anchor':'__unparsed__','level':2,'content':[],'sourceUnits':[]})
    for index,section in enumerate(out,1):
        section['sectionIndex']=index
        for block in section['sourceUnits']:
            unit_records=[]
            for unit_index,value in enumerate(block.get('unitTexts') or [block['text']],1):
                unit_records.append({'id':stable_id(article['url'],section['anchor'],str(index),str(block['blockIndex']),str(unit_index),block['tag'],value),
                    'tag':block['tag'],'text':value,'blockIndex':block['blockIndex'],'unitIndex':unit_index,'href':block.get('href',''),
                    'title':block.get('title',''),'class':block.get('class',''),'src':block.get('src',''),'alt':block.get('alt','')})
            block['units']=unit_records
    return out
def stable_id(*parts): return hashlib.sha1('\x1f'.join(parts).encode()).hexdigest()[:16]
def _split_long_text(value, max_chars):
    """Split a single long paragraph without dropping any source text."""
    value=re.sub(r'\s+',' ',value).strip()
    if len(value)<=max_chars: return [value]
    pieces=[]
    for part in re.split(r'(?<=[。！？；.!?;])',value):
        part=part.strip()
        if not part: continue
        while len(part)>max_chars:
            cut=part.rfind('，',0,max_chars+1)
            if cut<max_chars//2: cut=part.rfind(' ',0,max_chars+1)
            if cut<max_chars//2: cut=max_chars
            pieces.append(part[:cut].strip())
            part=part[cut:].lstrip('，, ')
        if part: pieces.append(part)
    return pieces
def _content_chunks(content, max_chars=1400):
    """Group complete paragraphs into readable cards, preserving all text."""
    paragraphs=[]
    for value in content:
        paragraphs.extend(_split_long_text(value,max_chars))
    chunks=[]; current=[]; size=0
    for paragraph in paragraphs:
        if not paragraph: continue
        extra=len(paragraph)+(1 if current else 0)
        if current and size+extra>max_chars:
            chunks.append(' '.join(current)); current=[]; size=0
        current.append(paragraph); size+=len(paragraph)+(1 if len(current)>1 else 0)
    if current: chunks.append(' '.join(current))
    return chunks
def _content_chunks_with_units(section,max_chars=1400):
    """Group readable source fragments while retaining exact source-unit IDs."""
    chunks=[]; current=[]; current_ids=[]; size=0
    for block in section['sourceUnits']:
        source_units=block.get('units',[])
        if not source_units:
            source_units=[{'id':stable_id(str(block.get('blockIndex','')),block['text']),'text':block['text']}]
        for unit in source_units:
            for fragment in _split_long_text(unit['text'],max_chars):
                if not fragment: continue
                extra=len(fragment)+(1 if current else 0)
                if current and size+extra>max_chars:
                    chunks.append({'text':' '.join(current),'knowledgeUnitIds':list(dict.fromkeys(current_ids))})
                    current=[]; current_ids=[]; size=0
                current.append(fragment); size+=len(fragment)+(1 if len(current)>1 else 0)
                current_ids.append(unit['id'])
    if current: chunks.append({'text':' '.join(current),'knowledgeUnitIds':list(dict.fromkeys(current_ids))})
    return chunks
def make_cards(source,article,path,content_hash=None):
    cards=[]
    for sec in sections(article):
        chunks=_content_chunks_with_units(sec)
        manual_review=not chunks
        review_tokens=('[图片需人工核对原文]','[交互图示需人工核对原文]','[SVG公式/图示需人工核对原文]','[MathML公式需人工核对原文]')
        source_units=[unit for block in sec.get('sourceUnits',[]) for unit in block.get('units',[])]
        has_practice_reference=any('/practice/q/' in unit.get('href','') or 'exam-tile' in unit.get('class','').split() for unit in source_units)
        if any(token in chunk['text'] for chunk in chunks for token in review_tokens): manual_review=True
        if any(unit.get('tag') in {'img','svg','canvas'} for unit in source_units): manual_review=True
        if has_practice_reference: manual_review=True
        if manual_review and not chunks:
            chunks=[{'text':'原文内容未能可靠提取。请打开来源链接，人工核对本节正文、公式、表格或图示后补录；在核对前不要将本卡作为已掌握知识。','knowledgeUnitIds':[]}]
        anchor=sec['anchor']
        base_id=stable_id(source['id'],path,sec['heading'],anchor)
        section_key=stable_id(source['id'],path,'section',anchor,str(sec['sectionIndex']),'' if anchor else sec['heading'])
        for part_index,chunk in enumerate(chunks,1):
            answer=repair_summary_text(article['url'], chunk['text']); unit_ids=chunk['knowledgeUnitIds']
            card_id=base_id if part_index==1 else stable_id(source['id'],path,sec['heading'],anchor,f'part-{part_index}')
            suffix=f'（第 {part_index}/{len(chunks)} 部分）' if len(chunks)>1 else ''
            question=f'请解释「{sec["heading"]}」本部分的关键概念、条件、过程与结论。{suffix}'
            locator=f'{sec.get("headingPath",sec["heading"])}（章节 {sec["sectionIndex"]}）'
            evidence=f'来源定位：{article["url"]}#{anchor} · {locator}；知识单元 ID：{", ".join(unit_ids) if unit_ids else "待人工核验"}'
            extraction_flags=['generic-question-pending-review','408-syllabus-mapping-pending','exam-evidence-pending']
            if manual_review: extraction_flags.append('source-extraction-incomplete')
            if has_practice_reference:
                extraction_flags.append('linked-question-index-not-question-content')
            cards.append({'id':card_id,'sourceId':source['id'],'articlePath':path,'articleTitle':article['title'],'articleUrl':article['url']+('#'+anchor if anchor else ''),'section':sec['heading'],'sectionHeadingPath':sec.get('headingPath',sec['heading']),'sectionAnchor':anchor,'sectionIndex':sec['sectionIndex'],'sectionKey':section_key,'sectionLevel':sec['level'],'part':part_index,'partCount':len(chunks),'knowledgeUnitIds':unit_ids,'knowledgeUnitReviewStatus':'candidate-unreviewed','provenance':{'articleUrl':article['url'],'sectionAnchor':anchor,'sectionIndex':sec['sectionIndex'],'sectionHeadingPath':locator,'knowledgeUnitIds':unit_ids,'sourceHash':content_hash,'verificationStatus':'not-reviewed'},'examPoints':[],'auditFlags':extraction_flags,'question':question,'answer':answer,'generatedQuestion':question,'generatedAnswer':answer,'evidence':evidence,'tags':[source['name']],'status':'needs-review','reviewReason':'source-extraction-incomplete' if manual_review else 'knowledge-point-and-408-review-required','origin':'source-summary','generatorVersion':4,**({'sourceHash':content_hash} if content_hash else {})})
    return cards
def merge_card(generated,old,source_changed=False):
    if not old: return generated
    merged={**generated,**old}
    merged.pop('sourceSectionRemoved',None)
    merged.pop('sourceArticleMissing',None)
    for key in ('sourceId','articlePath','articleTitle','articleUrl','section','sectionHeadingPath','sectionAnchor','sectionIndex','sectionKey','sectionLevel','part','partCount','origin','generatorVersion','sourceHash','generatedQuestion','generatedAnswer','reviewReason','knowledgeUnitIds','knowledgeUnitReviewStatus','provenance','examPoints','auditFlags'):
        if key in generated: merged[key]=generated[key]
        else: merged.pop(key,None)
    old_question=old.get('question','')
    old_answer=old.get('answer','')
    was_auto=old.get('origin')=='source-summary' and (
        (old.get('generatedQuestion') is not None and old_question==old.get('generatedQuestion') and old_answer==old.get('generatedAnswer')) or
        (old.get('status')=='inbox' and old_question==f'回忆「{old.get("section","")}」的核心定义、机制与易错点。' and old_answer==old.get('evidence')) or
        (old.get('suggestedAnswer') and old.get('suggestedAnswer')==old.get('generatedAnswer') and old.get('previousAnswer') is not None)
    )
    if source_changed and was_auto:
        merged['previousAnswer']=old_answer
        merged['question']=generated['question']
        merged['answer']=generated['answer']
        merged['evidence']=generated['evidence']
        merged['status']=generated['status']
        merged.pop('suggestedAnswer',None)
        merged.pop('suggestedQuestion',None)
    elif source_changed:
        merged['previousAnswer']=old_answer
        merged['suggestedAnswer']=generated['answer']
        merged['suggestedQuestion']=generated['question']
        merged['status']='needs-review'
    elif was_auto and old.get('generatorVersion',0)<generated.get('generatorVersion',0):
        merged['question']=generated['question']
        merged['answer']=generated['answer']
        merged['evidence']=generated['evidence']
        merged['status']=generated['status']
        merged.pop('suggestedAnswer',None)
        merged.pop('suggestedQuestion',None)
    if generated.get('knowledgeUnitReviewStatus')=='candidate-unreviewed' and old.get('generatorVersion',0)<generated.get('generatorVersion',0):
        merged['status']='needs-review'
        merged['reviewReason']=generated.get('reviewReason')
    return merged
def load(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return default
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); temp.replace(path)
def fetch(url,headers=None):
    req=Request(url,headers={'User-Agent':'CodeBrickStudyCards/0.1 (personal study project; low-rate sync)',**(headers or {})})
    with urlopen(req,timeout=30) as r: return r.read().decode(r.headers.get_content_charset() or 'utf-8',errors='replace'),dict(r.headers.items()),r.status
def sync(selected=None,limit=None,delay=.35,retry_failed=False):
    CACHE.mkdir(parents=True,exist_ok=True)
    prior_source_state=load(DATA/'sources.json',{'syncScope':None,'failedArticles':[]})
    retry_targets={item.get('url') for item in prior_source_state.get('failedArticles',[]) if item.get('url')} if retry_failed else set()
    if retry_failed and not retry_targets:
        print('没有失败文章需要重试',flush=True)
        return {'articles':len(load(DATA/'articles.json',{'articles':[]}).get('articles',[])),'cards':len(load(DATA/'cards/cards.json',{'cards':[]}).get('cards',[])),'failed':[]}
    # Make an interrupted refresh visible instead of leaving a stale "ok" flag.
    save(DATA/'sources.json',{'version':1,'sources':SOURCES,'syncedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'syncStatus':'in-progress','syncScope':('retry-failed' if retry_failed else (selected or 'all')),'failedArticles':prior_source_state.get('failedArticles',[]) if retry_failed else []})
    old_articles=load(DATA/'articles.json',{'articles':[]})['articles']; article_by_url={x['url']:x for x in old_articles}
    old_cards=load(DATA/'cards'/'cards.json',{'cards':[]})['cards']; cards_by_id={x['id']:x for x in old_cards}
    failed=[]; attempted_urls=set()
    for src in [x for x in SOURCES if selected is None or x['id']==selected]:
        print(f'[{src["id"]}] 获取文章清单',flush=True)
        try:
            raw,_,_=fetch(src['base']); m=re.search(r'__VP_HASH_MAP__\s*=\s*JSON\.parse\((".*?")\)',raw,re.S)
            if not m: raise RuntimeError(f'{src["id"]}: 找不到 VitePress 文章清单')
            mapping=json.loads(json.loads(m.group(1))); keys=sorted(k for k in mapping if k.startswith('posts_') and k.endswith('.md'))
        except Exception as e:
            failed.append({'sourceId':src['id'],'url':src['base'],'error':f'{type(e).__name__}: {e}'})
            print(f'来源清单失败 [{src["id"]}]: {e}',file=sys.stderr,flush=True)
            continue
        # Keep the complete manifest separate from the retry subset. A retry
        # run intentionally visits only failed URLs; treating that subset as
        # the source manifest would incorrectly mark untouched articles as removed.
        manifest_urls={src['base']+key[:-3].replace('_','/')+src['extension'] for key in keys}
        if retry_failed:
            keys=[key for key in keys if src['base']+key[:-3].replace('_','/')+src['extension'] in retry_targets]
        if limit is not None: keys=keys[:limit]
        listed_urls=manifest_urls
        print(f'[{src["id"]}] {len(keys)} 篇文章',flush=True)
        parsed_urls=set(); generated_ids_by_url={}
        for i,key in enumerate(keys,1):
            route=key[:-3].replace('_','/')
            url=src['base']+route+src['extension']
            attempted_urls.add(url)
            cache=CACHE/src['id']/(stable_id(url)+'.html'); cache.parent.mkdir(parents=True,exist_ok=True); previous=article_by_url.get(url,{})
            headers={}
            if previous.get('etag'): headers['If-None-Match']=previous['etag']
            if previous.get('lastModified'): headers['If-Modified-Since']=previous['lastModified']
            try:
                try: body,h,status=fetch(url,headers)
                except HTTPError as e:
                    if e.code!=304 or not cache.exists(): raise
                    body=cache.read_text(encoding='utf-8'); h=previous; status=304
                article=parse_article(body,url); digest=hashlib.sha256(json.dumps(article['blocks'],ensure_ascii=False).encode()).hexdigest()
                if not article['blocks']: raise ValueError('empty article body')
                generated=make_cards(src,article,route,digest)
                if not generated and any(card.get('sourceId')==src['id'] and card.get('articleUrl','').split('#',1)[0]==url for card in cards_by_id.values()):
                    raise ValueError('existing cards have no replacement; refusing to reconcile')
                changed=bool(previous.get('contentHash') and previous['contentHash']!=digest)
                rec={'sourceId':src['id'],'title':article['title'],'url':url,'cache':cache.relative_to(ROOT).as_posix(),'contentHash':digest,'etag':h.get('ETag') or h.get('etag'),'lastModified':h.get('Last-Modified') or h.get('last-modified'),'checkedAt':datetime.now(timezone.utc).isoformat(timespec='seconds')}
                if status!=304:
                    temp_cache=cache.with_suffix(cache.suffix+'.tmp')
                    temp_cache.write_text(body,encoding='utf-8')
                    temp_cache.replace(cache)
                article_by_url[url]=rec; parsed_urls.add(url)
                generated_ids_by_url[url]={card['id'] for card in generated}
                for card in generated:
                    cards_by_id[card['id']]=merge_card(card,cards_by_id.get(card['id']),changed)
                if i%20==0 or i==len(keys): print(f'[{src["id"]}] {i}/{len(keys)}',flush=True)
                time.sleep(delay)
            except Exception as e:
                failed.append({'sourceId':src['id'],'url':url,'error':f'{type(e).__name__}: {e}'})
                print(f'跳过 {url}: {e}',file=sys.stderr,flush=True)
        # Only a complete, non-retry run has enough information to reconcile
        # articles that disappeared from the source manifest.
        if limit is None and not retry_failed:
            for article in article_by_url.values():
                if article.get('sourceId') != src['id'] or article.get('url') in listed_urls: continue
                article['sourceArticleMissing']=True
                for card in cards_by_id.values():
                    if card.get('sourceId')==src['id'] and card.get('articleUrl','').split('#',1)[0]==article.get('url'):
                        card['sourceArticleMissing']=True
                        card['status']='needs-review'
        for card in cards_by_id.values():
            base_url=card.get('articleUrl','').split('#',1)[0]
            if card.get('sourceId')==src['id'] and base_url in parsed_urls and generated_ids_by_url.get(base_url) and card['id'] not in generated_ids_by_url[base_url]:
                card['sourceSectionRemoved']=True
                card['status']='needs-review'
        print(f'[{src["id"]}] 完成',flush=True)
        stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
        save(DATA/'sources.json',{'version':1,'sources':SOURCES,'syncedAt':stamp,'syncStatus':'in-progress','syncScope':'all' if selected is None else selected,'failedArticles':failed})
        save(DATA/'articles.json',{'version':1,'articles':sorted(article_by_url.values(),key=lambda x:(x['sourceId'],x['url']))})
        save(DATA/'cards'/'cards.json',{'version':1,'cards':list(cards_by_id.values())})
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    if retry_failed:
        for url in sorted(retry_targets-attempted_urls):
            failed.append({'sourceId':next((x['id'] for x in SOURCES if url.startswith(x['base'])),''),'url':url,'error':'URL absent from source manifest during retry'})
    prior_failures=prior_source_state.get('failedArticles',[])
    retry_completes_full_sync=(retry_failed and prior_source_state.get('syncScope')=='all' and all(item.get('url') not in {source['base'] for source in SOURCES} for item in prior_failures))
    full_sync=(selected is None and limit is None and not retry_failed) or retry_completes_full_sync
    final_status='incomplete' if failed else ('ok' if full_sync else 'partial')
    save(DATA/'sources.json',{'version':1,'sources':SOURCES,'syncedAt':stamp,'syncStatus':final_status,'syncScope':'all' if full_sync else (selected or 'retry-failed'),'failedArticles':failed})
    save(DATA/'articles.json',{'version':1,'articles':sorted(article_by_url.values(),key=lambda x:(x['sourceId'],x['url']))})
    save(DATA/'cards'/'cards.json',{'version':1,'cards':list(cards_by_id.values())})
    print(f'完成：{len(article_by_url)} 篇文章，{len(cards_by_id)} 张卡片（新卡先进入收件箱）')
    if failed:
        print(f'同步不完整：{len(failed)} 篇文章失败',file=sys.stderr,flush=True)
        for item in failed:
            print(f'  [{item["sourceId"]}] {item["url"]}: {item["error"]}',file=sys.stderr,flush=True)
        raise RuntimeError(f'同步不完整：{len(failed)} 个来源或文章失败')
    return {'articles':len(article_by_url),'cards':len(cards_by_id),'failed':failed}
def rebuild_cards_from_cache():
    """Regenerate cards from the last synchronized HTML snapshot without network access."""
    sources={item['id']:item for item in SOURCES}
    article_data=load(DATA/'articles.json',{'articles':[]})
    records=article_data.get('articles',[])
    cards_data=load(DATA/'cards'/'cards.json',{'cards':[]})
    cards_by_id={item['id']:item for item in cards_data.get('cards',[]) if item.get('id')}
    failed=[]; generated_ids_by_url={}; processed=set()
    for index,record in enumerate(records,1):
        source=sources.get(record.get('sourceId'))
        url=record.get('url','')
        cache_path=ROOT/record.get('cache','')
        try:
            if not source: raise ValueError('unknown sourceId')
            if not cache_path.is_file(): raise FileNotFoundError(f'cache not found: {record.get("cache")}')
            raw=cache_path.read_text(encoding='utf-8')
            article=parse_article(raw,url)
            digest=hashlib.sha256(json.dumps(article['blocks'],ensure_ascii=False).encode()).hexdigest()
            route=url[len(source['base']):]
            if source['extension'] and route.endswith(source['extension']): route=route[:-len(source['extension'])]
            generated=make_cards(source,article,route,digest)
            if not generated: raise ValueError('no section cards generated')
            previous_hash=record.get('contentHash')
            changed=bool(previous_hash and previous_hash!=digest)
            record.update({'title':article['title'],'contentHash':digest,'cardBuildAt':datetime.now(timezone.utc).isoformat(timespec='seconds')})
            article_data['articles'][index-1]=record
            processed.add(url)
            generated_ids_by_url[url]={card['id'] for card in generated}
            for card in generated:
                cards_by_id[card['id']]=merge_card(card,cards_by_id.get(card['id']),changed)
        except Exception as e:
            failed.append({'url':url,'error':f'{type(e).__name__}: {e}'})
    for card in cards_by_id.values():
        url=card.get('articleUrl','').split('#',1)[0]
        if url in processed and card.get('sourceId') in sources and card['id'] not in generated_ids_by_url[url]:
            card['sourceSectionRemoved']=True
            card['status']='needs-review'
    article_data['articles']=sorted(article_data.get('articles',[]),key=lambda x:(x.get('sourceId',''),x.get('url','')))
    save(DATA/'articles.json',article_data)
    save(DATA/'cards'/'cards.json',{'version':1,'cards':list(cards_by_id.values())})
    source_state=load(DATA/'sources.json',{'version':1,'sources':SOURCES})
    source_state['cardBuildAt']=datetime.now(timezone.utc).isoformat(timespec='seconds')
    source_state['cardGeneratorVersion']=4
    source_state['cardBuildStatus']='incomplete' if failed else 'ok'
    source_state['cardBuildFailures']=failed
    save(DATA/'sources.json',source_state)
    print(f'缓存重建：处理 {len(processed)}/{len(records)} 篇文章，生成/更新 {len(cards_by_id)} 张卡片；失败 {len(failed)} 篇')
    for item in failed: print(f'  {item["url"]}: {item["error"]}',file=sys.stderr)
    return {'articles':len(processed),'cards':len(cards_by_id),'failed':failed}

def main():
    ap=argparse.ArgumentParser(description='增量同步 CodeBrick 四门博客，生成带原文出处的记忆卡片候选')
    ap.add_argument('--source',choices=[x['id'] for x in SOURCES]); ap.add_argument('--limit',type=int); ap.add_argument('--delay',type=float,default=.35)
    ap.add_argument('--rebuild-cards-from-cache',action='store_true',help='仅使用本地已保存 HTML 重建卡片，不联网')
    ap.add_argument('--retry-failed',action='store_true',help='只重试 data/sources.json 中记录的失败文章')
    a=ap.parse_args()
    try:
        if a.rebuild_cards_from_cache: rebuild_cards_from_cache()
        else: sync(a.source,a.limit,a.delay,retry_failed=a.retry_failed)
    except RuntimeError as e:
        print(f'错误：{e}',file=sys.stderr,flush=True)
        return 1
    return 0
if __name__=='__main__': raise SystemExit(main())
