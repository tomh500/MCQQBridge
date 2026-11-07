"""Reproducible javac build for unobfuscated Minecraft 26.2; Gradle/Loom is also provided."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parents[1] / "_work/mcqq-mod-build"
CACHE = Path.home() / ".gradle/caches"
API = "0.161.0+26.2"


def get(url, target, expected=None):
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    if expected and hashlib.sha1(target.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Dependency checksum mismatch: " + target.name)
    return target


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    java_home = Path(os.environ.get("JAVA_HOME", "C:/Program Files/Java/jdk-25"))
    suffix = ".exe" if os.name == "nt" else ""
    javac = str(java_home/"bin"/("javac"+suffix))
    java = str(java_home/"bin"/("java"+suffix))
    minecraft_dir = CACHE / "fabric-loom/26.2"
    minecraft_dir.mkdir(parents=True, exist_ok=True)
    if not (minecraft_dir/"mojang_minecraft_info.json").is_file():
        versions=json.load(urllib.request.urlopen("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",timeout=20))
        entry=next(v for v in versions["versions"] if v["id"]=="26.2")
        get(entry["url"],minecraft_dir/"mojang_minecraft_info.json",entry["sha1"])
    info = json.loads((minecraft_dir/"mojang_minecraft_info.json").read_text())
    minecraft = get(info["downloads"]["client"]["url"],minecraft_dir/"minecraft-client.jar",info["downloads"]["client"]["sha1"])
    url = f"https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/{API}/fabric-api-{API}.jar"
    checksum = urllib.request.urlopen(url+".sha1",timeout=15).read().decode().strip()
    archive = get(url,WORK/"fabric-api.jar",checksum)
    cp = [minecraft]
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.startswith("META-INF/jars/") and name.endswith(".jar"):
                path=WORK/Path(name).name; path.write_bytes(z.read(name)); cp.append(path)
    loaders=list((CACHE/"modules-2/files-2.1/net.fabricmc/fabric-loader/0.19.5").rglob("fabric-loader-0.19.5.jar"))
    loader=loaders[0] if loaders else get("https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar",WORK/"fabric-loader-0.19.5.jar")
    cp.append(loader)
    for library in info["libraries"]:
        artifact=library.get("downloads",{}).get("artifact")
        if not artifact: continue
        group,name,version=library["name"].split(":")[:3]
        expected_name=Path(artifact["path"]).name
        cached=list((CACHE/"modules-2/files-2.1"/group/name/version).rglob(expected_name))
        path=cached[0] if cached else get(artifact["url"],WORK/"libraries"/expected_name,artifact["sha1"])
        cp.append(path)
    classes=ROOT/"build/manual/classes"
    assert classes.resolve().is_relative_to((ROOT/"build").resolve())
    if classes.exists(): shutil.rmtree(classes)
    classes.mkdir(parents=True,exist_ok=True)
    sources=sorted((ROOT/"src/main/java").rglob("*.java"))
    args=["--release","25","-proc:none","-encoding","UTF-8","-classpath",os.pathsep.join(str(p).replace("\\","/") for p in cp),"-d",str(classes).replace("\\","/")]
    args += [str(p).replace("\\","/") for p in sources]
    argfile=WORK/"javac.args"
    argfile.write_text("\n".join('"'+a+'"' for a in args),encoding="utf8")
    subprocess.run([javac,"@"+str(argfile)],check=True)
    probe=ROOT/"src/test/java/top/luotiany1/mcqq/images/DecoderProbe.java"
    test_classes=ROOT/"build/manual/test"; test_classes.mkdir(parents=True,exist_ok=True)
    subprocess.run([javac,"--release","25","-encoding","UTF-8","-cp",str(classes),"-d",str(test_classes),str(probe)],check=True)
    subprocess.run([java,"-Djava.awt.headless=true","-cp",os.pathsep.join([str(classes),str(test_classes)]),"top.luotiany1.mcqq.images.DecoderProbe"],check=True)
    output=ROOT/"build/libs/mcqq-images-1.0.0+26.2.jar"; output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as z:
        for p in classes.rglob("*.class"): z.write(p,p.relative_to(classes).as_posix())
        z.writestr("fabric.mod.json",(ROOT/"src/main/resources/fabric.mod.json").read_text().replace("${version}","1.0.0+26.2"))
    dist=ROOT.parent/"dist"; dist.mkdir(exist_ok=True); shutil.copy2(output,dist/output.name)
    print("Built and verified:",output)
    print("SHA-256:",hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__": main()
