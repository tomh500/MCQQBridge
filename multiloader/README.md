# Forge / NeoForge client (experimental)

Shared 26.2/26.3 client-only image logic and chat mixins live in `src/main/java`; `forge` and `neoforge` provide loader-specific metadata and builds. The implementation targets the unobfuscated 26.x client APIs and does not target earlier versions. Do not install a Fabric, Forge, or NeoForge image mod together: they share the same mod ID.

Build with JDK 25. From `neoforge`, run `gradlew build` for NeoForge 26.3, or `gradlew build -Pneo_version=26.2.0.93` for 26.2. From `forge`, run `gradlew build` for Forge 26.3, or `gradlew build -Pminecraft_version=26.2 -Pforge_version=65.1.3` for 26.2. Where a network proxy is required, Gradle and its child Java processes must both be configured to use it.

These are development builds. The full client acceptance matrix, including chat position, scrolling, animated images, resource cleanup, and interaction with third-party chat mods, must pass before release. Custom media hosts are configured in `config/mcqq-images.properties` as comma-separated, trailing-slash `trusted-media-bases`; the default trusts QQ image domains only.

The experimental unified JAR can be assembled with `python multiloader/package_all.py` after building the Fabric universal JAR and the 26.2 Forge and NeoForge adapters into the paths used by the script. It verifies decoder source equality, rejects conflicting classes, and includes metadata for all three loaders. The unified JAR has started on NeoForge 26.2; other loader/version combinations and image interaction still need runtime testing.
