"""Build the Bedrock resource pack using Python's standard library."""

from pathlib import Path
from struct import pack
from zipfile import ZIP_DEFLATED, ZipFile
from zlib import compress, crc32


PROBE_ICON = (
    "................",
    "...##########...",
    "..#..........#..",
    ".#...oooo.....#.",
    ".#..o....o....#.",
    ".#.o......o...#.",
    ".#.o......o...#.",
    ".#.o......o...#.",
    ".#.o......o...#.",
    ".#..o....oo...#.",
    ".#...oooo.oo..#.",
    ".#.........oo.#.",
    ".#..........o.#.",
    "..#..........#..",
    "...##########...",
    "................",
)
PALETTE = {
    ".": bytes((0, 0, 0, 0)),
    "#": bytes((44, 75, 108, 255)),
    "o": bytes((95, 213, 183, 255)),
}


def png_chunk(name, payload):
    return pack(">I", len(payload)) + name + payload + pack(">I", crc32(name + payload))


def create_icon():
    width = len(PROBE_ICON[0])
    height = len(PROBE_ICON)
    pixels = b"".join(b"\0" + b"".join(PALETTE[pixel] for pixel in row) for row in PROBE_ICON)
    header = pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", compress(pixels))
        + png_chunk(b"IEND", b"")
    )


def main():
    source = Path(__file__).resolve().parent
    output = source.parent / "build" / "MasterGAL.mcpack"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.write(source / "manifest.json", "manifest.json")
        archive.writestr("textures/ui/mastergal/probe.png", create_icon())
    print(output)


if __name__ == "__main__":
    main()
