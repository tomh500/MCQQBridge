"""Java 21 universal build. No Minecraft code, Fabric API, or assets are bundled."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'.cache'
VERSIONS=['1.21.4','1.21.5','1.21.6','1.21.7','1.21.8','1.21.9','1.21.10','1.21.11','26.1','26.1.1','26.1.2','26.2','26.3']
sys.path.insert(0,str(ROOT/'tools'))
from bindings import generate

def get(url,path,sha1=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        data=urllib.request.urlopen(url,timeout=60).read()
        if sha1 and hashlib.sha1(data).hexdigest()!=sha1:raise ValueError('Checksum: '+str(path))
        path.write_bytes(data)
    if sha1 and hashlib.sha1(path.read_bytes()).hexdigest()!=sha1:raise ValueError('Checksum: '+str(path))
    return path

def dependencies():
    lock=ROOT/'versions.lock.json'
    if lock.exists(): specs=json.loads(lock.read_text())
    else:
        manifest=json.load(urllib.request.urlopen('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json',timeout=30))
        api_xml=ET.fromstring(urllib.request.urlopen('https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/maven-metadata.xml',timeout=30).read())
        apis=[e.text for e in api_xml.findall('./versioning/versions/version')]
        specs={}
        for version in VERSIONS:
            entry=next(v for v in manifest['versions'] if v['id']==version)
            info_path=get(entry['url'],CACHE/version/'version.json',entry['sha1'])
            info=json.loads(info_path.read_text())
            choices=[v for v in apis if v.endswith('+'+version)]
            if not choices:raise ValueError('No Fabric API for '+version)
            api=max(choices,key=lambda v:tuple(int(x) for x in v.split('+')[0].split('.')))
            url=f'https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/{api}/fabric-api-{api}.jar'
            specs[version]={'metadata':entry,'downloads':info['downloads'],'fabric_api':api,'api_url':url,'api_sha1':urllib.request.urlopen(url+'.sha1').read().decode().strip()}
        lock.write_text(json.dumps(specs,indent=2)+'\n')
    def fetch(pair):
        version,spec=pair; folder=CACHE/version; entry=spec['metadata']
        get(entry['url'],folder/'version.json',entry['sha1'])
        for kind in ['client','client_mappings']:
            if kind not in spec['downloads']:continue
            download=spec['downloads'][kind]
            get(download['url'],folder/('client.jar' if kind=='client' else 'client.txt'),download['sha1'])
        if 'client_mappings' in spec['downloads']:
            url=f'https://maven.fabricmc.net/net/fabricmc/intermediary/{version}/intermediary-{version}.jar'
            sha=urllib.request.urlopen(url+'.sha1',timeout=30).read().decode().strip()
            archive=get(url,folder/'intermediary.jar',sha)
            with zipfile.ZipFile(archive) as z:(folder/'intermediary.tiny').write_bytes(z.read('mappings/mappings.tiny'))
        get(spec['api_url'],folder/'fabric-api.jar',spec['api_sha1'])
        print('Dependencies verified:',version,flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(fetch,specs.items()))
    return specs

def main():
    specs=dependencies()
    report=generate(CACHE,ROOT/'build/resources/bindings')
    from verify_matrix import verify
    verify(specs,CACHE)
    java_home=Path(os.environ.get('JAVA_HOME','C:/Program Files/Java/jdk-25' if os.name=='nt' else '/opt/jdk-25'))
    def executable(name):
        path=java_home/'bin'/(name+('.exe' if os.name=='nt' else ''))
        return str(path) if path.exists() else name
    loader_url='https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar'
    loader=get(loader_url,CACHE/'fabric-loader.jar',urllib.request.urlopen(loader_url+'.sha1').read().decode().strip())
    classes=ROOT/'build/classes'
    assert classes.resolve().is_relative_to((ROOT/'build').resolve())
    if classes.exists():shutil.rmtree(classes)
    classes.mkdir(parents=True,exist_ok=True)
    sources=list((ROOT/'src/main/java').rglob('*.java'))
    subprocess.run([executable('javac'),'--release','21','-proc:none','-encoding','UTF-8','-cp',str(loader),'-d',str(classes),*map(str,sources)],check=True)
    # Compile the 26.2 chat renderer against its exact public client API.
    subprocess.run([sys.executable,str(ROOT.parent/'build.py')],check=True)
    # Exercise the actual 26.3 text splitter as well as the 26.2 probe above.
    info=json.loads((CACHE/'26.3/version.json').read_text())
    deps=[CACHE/'26.3/client.jar']
    gradle=Path.home()/'.gradle/caches/modules-2/files-2.1'
    for library in info['libraries']:
        artifact=library.get('downloads',{}).get('artifact')
        if not artifact: continue
        group,name,version=library['name'].split(':')[:3]
        filename=Path(artifact['path']).name
        cached=list((gradle/group/name/version).rglob(filename))
        deps.append(cached[0] if cached else get(artifact['url'],CACHE/'26.3/libraries'/filename,artifact['sha1']))
    probe_dir=ROOT/'build/layout-26.3';probe_dir.mkdir(parents=True,exist_ok=True)
    classpath=os.pathsep.join(map(str,deps))
    probe=ROOT.parent/'src/test/java/top/luotiany1/mcqq/images/ChatLayoutProbe.java'
    subprocess.run([executable('javac'),'--release','21','-encoding','UTF-8','-cp',classpath,'-d',str(probe_dir),str(probe)],check=True)
    subprocess.run([executable('java'),'-Djava.awt.headless=true','-cp',os.pathsep.join([str(probe_dir),classpath]),'top.luotiany1.mcqq.images.ChatLayoutProbe'],check=True)
    # Exercise the actual universal message adapter with 26.2 and 26.3 classes.
    adapter_probe=ROOT.parent/'src/test/java/top/luotiany1/mcqq/images/UniversalChatProbe.java'
    loader_classpath=os.pathsep.join([str(classes),str(loader),str(ROOT/'build/resources')])
    for mc_version in ('26.2','26.3'):
        game_jar=CACHE/mc_version/'client.jar'
        game_classpath=os.pathsep.join([loader_classpath,str(game_jar),*(str(p) for p in deps[1:])])
        subprocess.run([executable('javac'),'--release','21','-encoding','UTF-8','-cp',game_classpath,'-d',str(probe_dir),str(adapter_probe)],check=True)
        subprocess.run([executable('java'),'-Djava.awt.headless=true','-cp',os.pathsep.join([str(probe_dir),game_classpath]),'top.luotiany1.mcqq.images.UniversalChatProbe',mc_version],check=True)
    tests=ROOT/'build/test'
    assert tests.resolve().is_relative_to((ROOT/'build').resolve())
    if tests.exists():shutil.rmtree(tests)
    tests.mkdir(exist_ok=True)
    subprocess.run([executable('javac'),'--release','21','-encoding','UTF-8','-cp',os.pathsep.join([str(classes),str(loader)]),'-d',str(tests),*map(str,(ROOT/'src/test/java').rglob('*.java'))],check=True)
    for probe in ['DecoderProbe','UniversalProbe','ViewerProbe']:
        subprocess.run([executable('java'),'-Djava.awt.headless=true','-cp',os.pathsep.join(map(str,[classes,tests,loader])),'top.luotiany1.mcqq.images.'+probe],check=True)
    (ROOT/'build/compatibility-report.json').write_text(json.dumps({'versions':report,'status':'API declarations and core tests verified; in-game visual acceptance required'},indent=2)+'\n')
    output=ROOT/'build/libs/mcqq-images-1.2.0-beta.1-universal.jar';output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as jar:
        for folder in [classes,ROOT/'src/main/resources',ROOT/'build/resources']:
            for path in sorted(folder.rglob('*')):
                if path.is_file():jar.write(path,path.relative_to(folder).as_posix())
        jar.write(ROOT/'LICENSE','LICENSE')
    with zipfile.ZipFile(output) as jar:
        for name in jar.namelist():
            if name.endswith('.class'):
                assert int.from_bytes(jar.read(name)[6:8],'big')==65, 'All classes must run on Java 21'
    print('Universal JAR:',output)
    print('SHA256:',hashlib.sha256(output.read_bytes()).hexdigest())

if __name__=='__main__':main()
