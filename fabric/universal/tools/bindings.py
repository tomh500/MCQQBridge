"""Generate the small Mojang-name -> Fabric intermediary bridge used by the universal JAR.

Only names/descriptors for classes this mod uses are shipped; no Minecraft code or assets.
"""
import json, re, zipfile
from pathlib import Path

CLASSES = {
    'net.minecraft.client.Minecraft', 'net.minecraft.network.chat.Component',
    'net.minecraft.network.chat.Style', 'net.minecraft.network.chat.ClickEvent',
    'net.minecraft.network.chat.ClickEvent$OpenUrl', 'net.minecraft.network.chat.ClickEvent$Action',
    'net.minecraft.network.chat.MutableComponent', 'net.minecraft.network.chat.FormattedText',
    'net.minecraft.client.gui.GuiGraphics', 'net.minecraft.client.gui.GuiGraphicsExtractor',
    'net.minecraft.client.gui.Gui', 'net.minecraft.client.gui.Hud', 'net.minecraft.client.Options', 'net.minecraft.client.OptionInstance',
    'net.minecraft.client.gui.Font', 'net.minecraft.client.gui.components.ChatComponent',
    'net.minecraft.client.gui.screens.ChatScreen', 'net.minecraft.client.GuiMessage$Line',
    'net.minecraft.client.input.MouseButtonEvent',
    'net.minecraft.util.FormattedCharSequence', 'net.minecraft.util.FormattedCharSink',
    'net.minecraft.network.chat.contents.PlainTextContents',
    'net.minecraft.resources.ResourceLocation',
    'net.minecraft.resources.Identifier', 'com.mojang.blaze3d.platform.NativeImage',
    'net.minecraft.client.renderer.texture.DynamicTexture',
    'net.minecraft.client.renderer.texture.TextureManager', 'net.minecraft.client.renderer.RenderType',
    'net.minecraft.client.renderer.RenderPipelines', 'net.minecraft.util.thread.BlockableEventLoop',
    'net.minecraft.util.thread.ReentrantBlockableEventLoop',
}
PRIMITIVES = dict(zip(['void','boolean','byte','char','short','int','long','float','double'], 'VZBCSIJFD'))

def mappings(folder):
    classes, members, owner = {}, [], None
    for line in (folder/'client.txt').read_text().splitlines():
        if not line or line.startswith('#'): continue
        if not line.startswith(' '):
            owner, obf = line[:-1].split(' -> '); classes[owner] = obf
        else:
            left, obf = line.strip().split(' -> ')
            left = re.sub(r'^\d+:\d+:', '', left)
            left = re.sub(r':\d+(?::\d+)?$', '', left)
            members.append((owner, left, obf))
    inter_c, inter_m, inter_f, current = {}, {}, {}, None
    for line in (folder/'intermediary.tiny').read_text().splitlines()[1:]:
        cols=line.split('\t')
        if cols[0]=='CLASS': inter_c[cols[1]]=cols[2]
        elif cols[0] in ('METHOD','FIELD'):
            (inter_m if cols[0]=='METHOD' else inter_f)[(cols[1],cols[3],cols[2])]=cols[4]
        elif cols[0]=='c': current=cols[1]; inter_c[current]=cols[2]
        elif len(cols)>4 and cols[1] in ('m','f'):
            (inter_m if cols[1]=='m' else inter_f)[(current,cols[3],cols[2])]=cols[4]
    def desc(name):
        if name.endswith('[]'): return '['+desc(name[:-2])
        return PRIMITIVES.get(name) or 'L'+classes.get(name,name).replace('.','/')+';'
    out={}
    for name in CLASSES & classes.keys():
        obf=classes[name].replace('.','/'); out['c|'+name]=inter_c.get(obf,obf).replace('/','.')
    for owner, left, obf_name in members:
        if owner not in CLASSES: continue
        typ, signature=left.split(' ',1); obf_owner=classes[owner].replace('.','/')
        if '(' in signature:
            name,args=signature.split('(',1); args=args.split(')',1)[0]
            descriptor='('+''.join(desc(a) for a in args.split(',') if a)+')'+desc(typ)
            inter_name=inter_m.get((obf_owner,obf_name,descriptor),obf_name)
            if name=='<init>': continue
            out.setdefault('m|'+owner+'|'+name,set()).add(inter_name)
        else:
            descriptor=desc(typ)
            out['f|'+owner+'|'+signature]=inter_f.get((obf_owner,obf_name,descriptor),obf_name)
    return {k:','.join(sorted(v)) if isinstance(v,set) else v for k,v in out.items()}

def generate(cache, output):
    output.mkdir(parents=True,exist_ok=True)
    reports=[]
    for folder in sorted(cache.iterdir()):
        if not (folder/'version.json').exists():continue
        obfuscated=(folder/'client.txt').exists()
        props=mappings(folder) if obfuscated else {}
        if obfuscated:
            assert props['c|net.minecraft.client.Minecraft'].startswith('net.minecraft.class_'), 'Intermediary class mapping missing: '+folder.name
            assert props['m|net.minecraft.client.Minecraft|getInstance'].startswith('method_'), 'Intermediary method mapping missing: '+folder.name
            assert props['f|net.minecraft.client.Minecraft|font'].startswith('field_'), 'Intermediary field mapping missing: '+folder.name
            required=['c|net.minecraft.client.Minecraft','m|net.minecraft.client.Minecraft|getInstance',
                'm|net.minecraft.client.gui.GuiGraphics|blit','m|com.mojang.blaze3d.platform.NativeImage|setPixel',
                'm|net.minecraft.network.chat.Component|getStyle', 'm|net.minecraft.network.chat.Component|getString',
                'm|net.minecraft.client.renderer.texture.TextureManager|register']
            missing=[k for k in required if k not in props]
            if missing:raise ValueError((folder.name,missing))
        props['version']=folder.name
        (output/(folder.name+'.properties')).write_text('\n'.join(k+'='+v for k,v in sorted(props.items()))+'\n',encoding='ascii')
        reports.append({'minecraft':folder.name,'namespace':'intermediary' if obfuscated else 'official','bindings':len(props)})
    return reports
