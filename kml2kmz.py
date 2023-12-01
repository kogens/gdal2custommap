import argparse
import logging
import re
import zipfile
from pathlib import Path

from xml.dom.minidom import parse


def htc(m):
    return chr(int(m.group(1), 16))


def urldecode(url):
    rex = re.compile('%([0-9a-hA-H][0-9a-hA-H])', re.M)
    return rex.sub(htc, url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Convert KML file to KMZ (Garmin CustomMap) file'
    )
    parser.add_argument('src_file', metavar='src_file', type=str, help='Source file')

    parser.add_argument('-o', '--outfile', dest="outfile", metavar="FILE", help="Write output to FILE")
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    # check for KML
    src_file = Path(args.src_file)

    if not src_file.exists():
        parser.error(f'Unable to find KML: {src_file}')

    if not args.outfile:
        # If no output file is given, use input filename with .kmz extension
        args.outfile = src_file.with_suffix('.kmz')
    logging.info("Output to", args.outfile)

    # create the output zip file
    zipped = zipfile.ZipFile(args.outfile, 'w', zipfile.ZIP_DEFLATED)

    # read the source xml
    kml = parse(str(src_file))
    nodes = kml.getElementsByTagName('href')

    base = src_file.parent

    for node in nodes:
        href = node.firstChild

        img = Path(urldecode(href.nodeValue).replace('file:///', ''))
        if not img.exists():
            img = base / img

        if not img.exists():
            parser.error(f'Unable to find image: {img}')

        # add the image
        filename = Path('files') / img.name
        logging.debug(f"Storing {img} as {filename}")
        zipped.write(img, filename, zipfile.ZIP_STORED)

        # modify the xml to point to the correct image
        href.nodeValue = filename

    logging.debug("Storing KML as doc.kml")
    zipped.writestr('doc.kml', kml.toxml("UTF-8"))

    zipped.close()
    logging.info("Finished")
