"""Check the actual class files of all thirteen releases without launching Minecraft."""
import io
import re
import struct
import zipfile

def classfile(data):
    stream=io.BytesIO(data)
    def u1():return struct.unpack('>B',stream.read(1))[0]
    def u2():return struct.unpack('>H',stream.read(2))[0]
    def u4():return struct.unpack('>I',stream.read(4))[0]
    assert u4()==0xCAFEBABE
    u2();major=u2(); count=u2();pool=[None]*count;i=1
    while i<count:
        tag=u1()
        if tag==1:pool[i]=stream.read(u2()).decode('utf-8',errors='replace')
        elif tag in (7,8,16,19,20):pool[i]=u2()
        elif tag in (3,4):stream.read(4)
        elif tag in (5,6):stream.read(8);i+=1
        elif tag in (9,10,11,12,17,18):stream.read(4)
        elif tag==15:stream.read(3)
        else:raise ValueError('Class tag '+str(tag))
        i+=1
    flags=u2();name=pool[pool[u2()]];super_index=u2();parent=pool[pool[super_index]] if super_index else None
    interfaces=[pool[pool[u2()]] for _ in range(u2())]
    def attributes():
        for _ in range(u2()):u2();stream.read(u4())
    def members():
        result=[]
        for _ in range(u2()):
            access=u2();n=pool[u2()];desc=pool[u2()];attributes();result.append((n,desc,access))
        return result
    fields=members();methods=members()
    return {'name':name,'parent':parent,'interfaces':interfaces,'fields':fields,'methods':methods,'major':major}

def verify(specs,cache):
    for version in specs:
        folder=cache/version; archive=zipfile.ZipFile(folder/'client.jar')
        proguard={};members={};owner=None
        if (folder/'client.txt').exists():
            for line in (folder/'client.txt').read_text().splitlines():
                if not line or line.startswith('#'):continue
                if not line.startswith(' '):owner,obf=line[:-1].split(' -> ');proguard[owner]=obf
                else:
                    left,obf=line.strip().split(' -> ');left=re.sub(r'^\d+:\d+:','',left);left=re.sub(r':\d+(?::\d+)?$','',left)
                    typ,signature=left.split(' ',1);name=signature.split('(')[0]
                    members.setdefault((owner,name),set()).add(obf)
        loaded={}
        def load(owner):
            internal=proguard.get(owner,owner).replace('.','/')
            if internal not in loaded:loaded[internal]=classfile(archive.read(internal+'.class'))
            return loaded[internal]
        def public_method(owner,name,argc=None):
            names=members.get((owner,name),{name});info=load(owner)
            found=[m for m in info['methods'] if m[0] in names and m[2]&1]
            if argc is not None:found=[m for m in found if len(re.findall(r'\[*L[^;]+;|\[*[ZBCSIJFD]',m[1].split(')')[0][1:]))==argc]
            assert found,(version,owner,name,argc)
            return found
        def field(owner,name):
            names=members.get((owner,name),{name})
            assert any(f[0] in names and f[2]&1 for f in load(owner)['fields']),(version,owner,name)
        modern=version.startswith('26.'); earliest=version=='1.21.4'
        mc='net.minecraft.client.Minecraft';gc='net.minecraft.client.gui.GuiGraphicsExtractor' if modern else 'net.minecraft.client.gui.GuiGraphics'
        public_method(mc,'getInstance',0);public_method(mc,'getTextureManager',0)
        for name in ['font','level','gui','options']:field(mc,name)
        public_method('net.minecraft.client.Options','chatVisibility',0); public_method('net.minecraft.client.OptionInstance','get',0)
        if modern and not version.startswith('26.1'):
            field('net.minecraft.client.gui.Gui','hud');public_method('net.minecraft.client.gui.Gui','screen',0);public_method('net.minecraft.client.gui.Hud','isHidden',0)
        else:
            field(mc,'options');field(mc,'screen');field('net.minecraft.client.Options','hideGui')
        owner='net.minecraft.client.gui.Hud' if modern and not version.startswith('26.1') else 'net.minecraft.client.gui.Gui'
        public_method(owner,'getChat',0); public_method(owner,'getGuiTicks',0)
        chat='net.minecraft.client.gui.components.ChatComponent'
        info=load(chat)
        for name in ('trimmedMessages','chatScrollbarPos'):
            assert any(f[0] in members.get((chat,name),{name}) for f in info['fields']),(version,chat,name)
        for name in ('getScale','getLineHeight','getWidth'):
            assert any(m[0] in members.get((chat,name),{name}) and m[1].startswith('()') for m in info['methods']),(version,chat,name)
        public_method(chat,'getLinesPerPage',0)
        line='net.minecraft.client.multiplayer.chat.GuiMessage$Line' if modern else 'net.minecraft.client.GuiMessage$Line'
        public_method(line,'content',0); public_method(line,'addedTime',0)
        public_method('net.minecraft.util.FormattedCharSequence','accept',1)
        public_method('net.minecraft.network.chat.Component','copy',0); public_method('net.minecraft.network.chat.Component','plainCopy',0); public_method('net.minecraft.network.chat.Component','getContents',0); public_method('net.minecraft.network.chat.Component','literal',1)
        public_method('net.minecraft.network.chat.contents.PlainTextContents','text',0)
        public_method('net.minecraft.network.chat.Style','getInsertion',0); public_method('net.minecraft.network.chat.Style','withInsertion',1); field('net.minecraft.network.chat.Style','EMPTY')
        public_method('net.minecraft.network.chat.MutableComponent','setStyle',1); public_method('net.minecraft.network.chat.MutableComponent','append',1)
        public_method(gc,'enableScissor',4); public_method(gc,'disableScissor',0)
        public_method('net.minecraft.util.thread.BlockableEventLoop','execute',1)
        for name,argc in [('getString',0),('getStyle',0),('getSiblings',0)]:public_method('net.minecraft.network.chat.Component',name,argc)
        public_method('net.minecraft.network.chat.Style','getClickEvent',0)
        if earliest:
            public_method('net.minecraft.network.chat.ClickEvent','getAction',0);public_method('net.minecraft.network.chat.ClickEvent','getValue',0);field('net.minecraft.network.chat.ClickEvent$Action','OPEN_URL')
        else:public_method('net.minecraft.network.chat.ClickEvent$OpenUrl','uri',0)
        resource='net.minecraft.resources.Identifier' if modern or version=='1.21.11' else 'net.minecraft.resources.ResourceLocation'
        public_method(resource,'fromNamespaceAndPath',2)
        for name,argc in [('guiWidth',0),('guiHeight',0),('fill',5),('text' if modern else 'drawString',5),('blit',12)]:public_method(gc,name,argc)
        public_method('net.minecraft.client.gui.Font','plainSubstrByWidth',2)
        constructors=public_method('net.minecraft.client.renderer.texture.DynamicTexture','<init>',1 if earliest else 2)
        native='L'+proguard.get('com.mojang.blaze3d.platform.NativeImage','com.mojang.blaze3d.platform.NativeImage').replace('.','/')+';'
        assert any(m[1].startswith('('+('' if earliest else 'Ljava/util/function/Supplier;')+native+')') for m in constructors),(version,'texture constructor')
        assert any(m[1].startswith('([B)') for m in public_method('com.mojang.blaze3d.platform.NativeImage','read',1)),version
        for name,argc in [('register',2),('release',1)]:public_method('net.minecraft.client.renderer.texture.TextureManager',name,argc)
        if version in ['1.21.4','1.21.5']:public_method('net.minecraft.client.renderer.RenderType','guiTextured',1)
        else:field('net.minecraft.client.renderer.RenderPipelines','GUI_TEXTURED')
        # Verify callbacks against the Fabric API release for this exact Minecraft.
        api_classes={}
        with zipfile.ZipFile(folder/'fabric-api.jar') as api:
            for nested in api.namelist():
                if nested.startswith('META-INF/jars/') and nested.endswith('.jar'):
                    with zipfile.ZipFile(io.BytesIO(api.read(nested))) as jar:
                        for path in jar.namelist():
                            if path.endswith('.class') and any(k in path for k in ['ClientReceiveMessageEvents','ClientPlayConnectionEvents','HudRenderCallback','HudElement','VanillaHudElements','ScreenEvents']):
                                api_classes[path[:-6]]=classfile(jar.read(path))
        base='net/fabricmc/fabric/api/client/'
        assert base+'message/v1/ClientReceiveMessageEvents$ModifyGame' in api_classes,version
        assert base+'screen/v1/ScreenEvents$AfterInit' in api_classes,version
        assert base+('screen/v1/ScreenEvents$AfterExtract' if modern else 'screen/v1/ScreenEvents$AfterRender') in api_classes,version
        game=api_classes[base+'message/v1/ClientReceiveMessageEvents$Game']
        assert any(m[1].endswith('Z)V') for m in game['methods'] if m[0]!='<clinit>'),(version,'GAME callback signature')
        assert base+'networking/v1/ClientPlayConnectionEvents$Disconnect' in api_classes,version
        if base+'rendering/v1/hud/HudElementRegistry' in api_classes:
            assert any(m[0]=='attachElementAfter' for m in api_classes[base+'rendering/v1/hud/HudElementRegistry']['methods']),version
            assert base+'rendering/v1/hud/VanillaHudElements' in api_classes,version
        else:assert base+'rendering/v1/HudRenderCallback' in api_classes,version
        print('Minecraft and Fabric API declarations verified:',version,flush=True)
