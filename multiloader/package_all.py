"""Package the three independently built client adapters into one test JAR."""
from pathlib import Path
import hashlib
import zipfile

ROOT=Path(__file__).resolve().parent.parent
DIST=ROOT/'dist/client'
FABRIC=ROOT/'fabric/universal/build/libs/mcqq-images-1.2.0-beta.1-universal.jar'
FORGE=DIST/'mcqq-images-forge-1.2.0-dev+26.2.jar'
NEO=DIST/'mcqq-images-neoforge-1.2.0-dev+26.2.jar'
OUTPUT=DIST/'mcqq-images-1.2.0-beta.1-all-loaders.jar'


def main():
    # The Java 21 implementation is bytecode-compatible and is shared with
    # Forge and NeoForge. Never silently merge divergent decoders.
    a=(ROOT/'fabric/universal/src/main/java/top/luotiany1/mcqq/images/ImageFrames.java').read_text().splitlines()
    b=(ROOT/'multiloader/src/main/java/top/luotiany1/mcqq/images/ImageFrames.java').read_text().splitlines()
    if a != b: raise RuntimeError('Image decoders differ; reconcile them before packaging')
    entries={}
    for file in (FABRIC,FORGE,NEO):
        with zipfile.ZipFile(file) as jar:
            if jar.testzip(): raise RuntimeError('Corrupt input '+str(file))
            for item in jar.infolist():
                if item.is_dir(): continue
                name=item.filename
                data=jar.read(item)
                if name=='META-INF/MANIFEST.MF' and file==NEO: continue
                if name.startswith('top/luotiany1/mcqq/images/ImageFrames') and file!=FABRIC: continue
                if name in ('META-INF/mods.toml','META-INF/neoforge.mods.toml'):
                    data=data.replace(b'1.2.0-dev',b'1.2.0-beta.1')
                if name in entries and entries[name]!=data: raise RuntimeError('Conflicting JAR entry: '+name)
                entries[name]=data
    required=['fabric.mod.json','META-INF/mods.toml','META-INF/neoforge.mods.toml','META-INF/MANIFEST.MF','mcqq-images.mixins.json']
    for name in required:
        if name not in entries: raise RuntimeError('Missing loader entry: '+name)
    if b'MixinConfigs: mcqq-images.mixins.json' not in entries['META-INF/MANIFEST.MF']:
        raise RuntimeError('Forge Mixin manifest is missing')
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED) as jar:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(name,(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            jar.writestr(info,data)
    with zipfile.ZipFile(OUTPUT) as jar:
        if jar.testzip(): raise RuntimeError('Output verification failed')
    print('Built:',OUTPUT)
    print('SHA-256:',hashlib.sha256(OUTPUT.read_bytes()).hexdigest())

if __name__=='__main__':main()
